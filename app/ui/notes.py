"""Background course-notes process with a bounded queue and explicit file destinations."""
from app.i18n import tr as _tr
from collections import deque
import json
from pathlib import Path
import sys
from PySide6.QtCore import QObject,Signal,QProcess,QProcessEnvironment
from app.asr.config import ROOT
from .lifetime import OwnerJob,JOB_ENV
from .protocol import EventDecoder


class NotesController(QObject):
    status_changed=Signal(str)
    busy_changed=Signal(bool)
    saved=Signal(dict)
    problem=Signal(str)

    def __init__(self,parent=None):
        super().__init__(parent);self.process=None;self.job=None;self.pending=deque();self.current=None
        self.decoder=None;self.done=False;self.failed=False;self.last_path=None;self.generation=0

    @property
    def busy(self):return self.current is not None or bool(self.pending)

    def generate(self,payload,directory):
        if not payload.get('records'):raise ValueError(_tr('还没有可整理的课程内容。'))
        if len(self.pending)>=4:raise ValueError(_tr('待整理课程已满，请完成当前任务后再生成。'))
        data=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        if len(data)>40*1024*1024:raise ValueError(_tr('课程材料超过处理上限。'))
        directory=Path(directory).resolve()
        if not directory.is_dir():raise ValueError(_tr('请选择可用的 AI 稿保存文件夹。'))
        self.pending.append((data,directory));self.busy_changed.emit(True)
        if self.current is None:self._start_next()
        else:self.status_changed.emit(f"{_tr('正在整理上一课程，另有 ')}{len(self.pending)}{_tr(' 次待整理。')}")

    def _start_next(self):
        if not self.pending:self.busy_changed.emit(False);return
        self.current=self.pending.popleft();self.decoder=EventDecoder();self.done=False;self.failed=False
        self.generation+=1;generation=self.generation
        try:self.job=OwnerJob()
        except OSError:
            self.current=None;self.pending.clear()
            self.status_changed.emit(_tr('AI 整理进程无法准备，请重新启动 ELT 后重试。'))
            self.problem.emit(_tr('AI 整理进程无法准备，请重新启动 ELT 后重试。'))
            self.busy_changed.emit(False);return
        process=QProcess(self);self.process=process
        env=QProcessEnvironment.systemEnvironment();env.insert(JOB_ENV,self.job.name);env.insert('PYTHONUTF8','1')
        process.setProcessEnvironment(env);process.setWorkingDirectory(str(ROOT));process.setProgram(sys.executable)
        process.setArguments(['-u','-m','app.notes.worker','--directory',str(self.current[1])])
        process.started.connect(lambda:self._send(process,generation))
        process.readyReadStandardOutput.connect(lambda:self._read(process,generation))
        process.readyReadStandardError.connect(lambda:process.readAllStandardError())
        process.finished.connect(lambda code,status:self._finished(process,generation,code))
        process.errorOccurred.connect(lambda error:self._process_error(process,generation,error))
        self.status_changed.emit(_tr('正在准备 AI 课程梳理…'));process.start()

    def _send(self,process,generation):
        if generation!=self.generation:return
        process.write(self.current[0]);process.closeWriteChannel()

    def _read(self,process,generation):
        data=bytes(process.readAllStandardOutput())
        if generation!=self.generation:return
        try:
            for value in self.decoder.feed(data):
                if value['event']=='notes_progress':
                    self.status_changed.emit(f"{_tr('正在整理课程细节 ')}{value['part']}/{value['parts']}…" if value.get('phase')=='details'
                                             else _tr('正在生成课程总览与复习提纲…'))
                elif value['event']=='notes_saved':
                    self.done=True;self.last_path=Path(value['path'])
                    self.status_changed.emit(_tr('AI 稿已保存：')+self.last_path.name)
                    self.saved.emit(value)
                elif value['event']=='notes_error':
                    self.failed=True;self.status_changed.emit(value['message']);self.problem.emit(value['message'])
        except (ValueError,KeyError,UnicodeError):
            self.failed=True;self.problem.emit(_tr('AI 整理返回数据异常，未确认生成完成。'))

    def _finished(self,process,generation,code):
        if generation!=self.generation:return
        self._read(process,generation)
        if not self.done and not self.failed:
            self.problem.emit(_tr('AI 整理已中断，原始翻译稿保留，可手动重试。'))
            self.status_changed.emit(_tr('AI 稿未生成，可手动重试。'))
        if self.job:self.job.close();self.job=None
        self.process=None;self.current=None;process.deleteLater();self._start_next()

    def _process_error(self,process,generation,error):
        if generation==self.generation and error==QProcess.FailedToStart:
            self.failed=True;self.problem.emit(_tr('AI 整理进程无法启动。'));self._finished(process,generation,1)

    def close(self):
        was_busy=self.busy
        self.generation+=1;self.pending.clear();self.current=None
        if self.process:
            process=self.process;self.process=None
            if process.state()!=QProcess.NotRunning:process.kill();process.finished.connect(process.deleteLater)
            else:process.deleteLater()
        if self.job:self.job.close();self.job=None
        if was_busy:self.busy_changed.emit(False)
