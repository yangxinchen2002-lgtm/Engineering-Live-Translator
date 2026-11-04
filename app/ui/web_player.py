"""The formal GUI owns the internal WebView2 player, independently of capture."""
from app.i18n import tr as _tr
import json
from PySide6.QtCore import QObject,QProcess,QProcessEnvironment,Signal
from app.asr.config import ROOT
from .lifetime import OwnerJob,JOB_ENV


class WebPlayer(QObject):
    problem=Signal(str)
    follow_requested=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.process=None;self.job=None;self.url='';self.closing=False;self.pending_local=False;self.output=b''

    def open(self,url=''):
        self.closing=False
        if self.process and self.process.state()!=QProcess.NotRunning:
            if url and url!=self.url:self.url=url;self.send('CONNECT',url=url)
            self.send('RAISE');return
        if self.job:self.job.close();self.job=None
        if self.process:self.process.deleteLater();self.process=None
        import sys
        self.job=OwnerJob();self.url=url
        process=QProcess(self);self.process=process
        process.setProgram(sys.executable);process.setWorkingDirectory(str(ROOT))
        process.setArguments(['-B','-X','utf8','-m','app.web_follow.player'])
        env=QProcessEnvironment.systemEnvironment();env.insert(JOB_ENV,self.job.name);env.insert('PYTHONUTF8','1')
        process.setProcessEnvironment(env)
        process.started.connect(self._started)
        process.readyReadStandardOutput.connect(lambda:self._read_output(process))
        process.readyReadStandardError.connect(lambda:process.readAllStandardError())
        process.finished.connect(lambda *a:self._finished(process))
        process.errorOccurred.connect(lambda e:self.problem.emit(_tr('课程播放窗口未能启动，请检查网页播放组件。')) if e==QProcess.FailedToStart else None)
        process.start()

    def _started(self):
        self.send('CONFIG',url=self.url)
        if self.pending_local:self.pending_local=False;self.send('PICK_LOCAL')

    def open_file(self,url=''):
        self.pending_local=True;self.open(url)
        if self.pending_local and self.process and self.process.state()==QProcess.Running:
            self.pending_local=False;self.send('PICK_LOCAL')

    def _read_output(self,process):
        raw=bytes(process.readAllStandardOutput())
        if process is not self.process or self.closing:return
        self.output+=raw
        if len(self.output)>32768:self.output=b'';return
        while b'\n' in self.output:
            line,self.output=self.output.split(b'\n',1)
            try:message=json.loads(line)
            except (ValueError,TypeError):continue
            if isinstance(message,dict) and message.get('event')=='player_follow_requested':self.follow_requested.emit()

    def send(self,command,**data):
        if self.process and self.process.state()==QProcess.Running:
            self.process.write((json.dumps(dict(command=command,**data),ensure_ascii=False)+'\n').encode())

    def disconnect(self):self.url='';self.send('DISCONNECT')

    def _finished(self,process):
        self.output=b''
        failed=process.exitCode()!=0 and not self.closing
        if self.process is process:
            if self.job:self.job.close();self.job=None
            self.process=None
        process.deleteLater()
        if failed:self.problem.emit(_tr('课程窗口意外退出，请检查 WebView2 运行环境，或切换到 Edge 扩展方式。'))

    def close(self):
        self.closing=True
        self.send('CLOSE')
        if self.process and not self.process.waitForFinished(3000):
            if self.job:self.job.close();self.job=None
            self.process.waitForFinished(2000)
