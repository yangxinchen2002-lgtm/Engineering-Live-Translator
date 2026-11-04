from __future__ import annotations
from app.i18n import tr as _tr
from collections import deque,OrderedDict
from pathlib import Path
import sys
import json
from PySide6.QtCore import QObject,Signal,Slot,QProcess,QProcessEnvironment,QTimer,QRunnable,QThreadPool
from app.asr.config import ROOT,ASRConfig
from app.audio.processes import ProcessSelector,ProcessInfo,source_executable,SOURCE_LABELS
from app.translation.credentials import manage_credential,store_credential,credential_error_message,CredentialStoreError
from .lifetime import OwnerJob,JOB_ENV
from .protocol import EventDecoder,SubtitleViewModel
from app.asr.clock import now_ns
from app.diagnostics.runtime import RuntimeMetrics
from app.notes.transcript import CourseTranscript
from app.languages import ASR_LANGUAGES
from app.translation.providers import provider_info,validate_model


class TaskSignals(QObject):
    done=Signal(str,object)
    failed=Signal(str,str)


class Task(QRunnable):
    def __init__(self,key,function):
        super().__init__();self.key=key;self.function=function;self.signals=TaskSignals()

    def run(self):
        try:self.signals.done.emit(self.key,self.function())
        except Exception as error:
            message=(credential_error_message(error) if self.key.split(':',1)[0] in ('credentials','credential_save')
                     else _tr('本机信息暂时无法读取，请重试。'))
            self.signals.failed.emit(self.key,message)
        finally:self.function=None


class BackendController(QObject):
    web_ready=Signal(str)
    web_voices_ready=Signal(object)
    event_received=Signal(dict)
    view_changed=Signal()
    subtitle_received=Signal(dict)
    running_changed=Signal(bool)
    pause_changed=Signal()
    finished=Signal(int,bool)
    problem=Signal(str)
    processes_ready=Signal(object,object)
    credentials_ready=Signal(dict)
    credential_saved=Signal(bool,str)
    credential_saved_for=Signal(str,bool,str)
    preferences_saved=Signal(object,bool)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.process=QProcess(self)
        self.process.setProcessChannelMode(QProcess.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._stdout)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.process.started.connect(self._process_started)
        self.pending_command=None;self.web_mode=False;self.web_clock={}
        self.decoder=EventDecoder();self.model=SubtitleViewModel()
        self.course=CourseTranscript()
        self.job=None;self.running=False;self.stopping=False;self.forced=False
        self.backend_pid=None;self.stderr_tail='';self.diagnostics=deque(maxlen=300)
        self.capture_target=None
        self.paused=False;self.pause_pending=False;self.audio_ready=False
        self.source_kind='sessions'
        self.translation_provider='deepseek'
        self.voice_language='zh'
        self.telemetry=RuntimeMetrics();self.generation=0;self.received_ns=0
        self.paint_records=OrderedDict()
        self.dirty=False
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(1)
        self.operations={};self.closed=False
        self.render_timer=QTimer(self);self.render_timer.setInterval(100)
        self.render_timer.timeout.connect(self._flush);self.render_timer.start()
        self.stop_timer=QTimer(self);self.stop_timer.setSingleShot(True);self.stop_timer.setInterval(20000)
        self.stop_timer.timeout.connect(self.force_stop)
        self.pause_timer=QTimer(self);self.pause_timer.setSingleShot(True);self.pause_timer.setInterval(10000)
        self.pause_timer.timeout.connect(self._pause_timeout)

    def _task(self,key,function,success,failure):
        if self.closed or key in self.operations:return
        task=Task(key,function);self.operations[key]=(task,success,failure)
        task.signals.done.connect(self._task_done);task.signals.failed.connect(self._task_failed)
        self.pool.start(task)

    @Slot(str,object)
    def _task_done(self,key,value):
        operation=self.operations.pop(key,None)
        if operation and not self.closed:operation[1](value)

    @Slot(str,str)
    def _task_failed(self,key,message):
        operation=self.operations.pop(key,None)
        if operation and not self.closed:operation[2](message)

    def refresh_processes(self):
        source=self.source_kind
        def ready(value):
            if source!=self.source_kind:self.refresh_processes();return
            self.processes_ready.emit(value[0],value[1])
        def failed(message):
            if source!=self.source_kind:self.refresh_processes();return
            self.problem.emit(message)
        self._task('processes',lambda:ProcessSelector().discover(source),ready,failed)

    def set_source_kind(self,source:str):
        source_executable(source)
        if self.running:raise RuntimeError(_tr('请先停止当前会话，再切换音频来源。'))
        self.source_kind=source
        self.processes_ready.emit([],[])
        self.refresh_processes()

    def refresh_credentials(self,provider=None):
        provider=provider or self.translation_provider;provider_info(provider)
        self._task('credentials:'+provider,lambda:manage_credential('status') if provider=='deepseek' else manage_credential('status',provider),
                   lambda status:self.credentials_ready.emit({**status,'provider':provider}),
                   lambda message:self.credentials_ready.emit({'available':False,'source':'read_error','error':message,'provider':provider}))

    def refresh_web_voices(self,language='zh'):
        from app.web_follow.speech import chinese_voices,voices_for
        if language not in ('zh','en'):raise ValueError('invalid system voice language')
        self.voice_language=language
        def ready(voices):
            if language!=self.voice_language:self.refresh_web_voices(self.voice_language);return
            self.web_voices_ready.emit(voices)
        self._task('web_voices',chinese_voices if language=='zh' else lambda:voices_for(language),ready,lambda message:ready([]))

    def _process_started(self):
        if self.pending_command is not None:
            data=self.pending_command;self.pending_command=None
            if self.process.write(data)!=len(data):
                self.problem.emit(_tr('网页服务配置无法送达，已停止启动。'));self.force_stop()

    def start_web(self,options,seconds=3600,transcript_directory=None):
        if self.running:raise RuntimeError(_tr('请先停止当前会话。'))
        if options.get('language') not in ASR_LANGUAGES:raise ValueError(_tr('课程语言无效。'))
        validate_model(options.get('provider'),options.get('model'))
        config=ASRConfig.load(ROOT/'config/asr.toml',language=options['language'],course_terms='')
        if not (Path(config.model)/'model.bin').is_file():raise FileNotFoundError(_tr('未找到本地识别模型。'))
        payload={**options,'seconds':seconds,'transcript_directory':str(transcript_directory) if transcript_directory else None}
        command=b'CONFIG '+json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')+b'\n'
        if len(command)>32768:raise ValueError(_tr('网页模式配置过大。'))
        self.decoder=EventDecoder();self.model.reset();self.course.reset();self.diagnostics.clear();self.stderr_tail=''
        self.telemetry=RuntimeMetrics();self.received_ns=0;self.paint_records.clear();self.web_clock={}
        self.process.readAllStandardOutput();self.process.readAllStandardError()
        self.stopping=self.forced=False;self.backend_pid=None;self.capture_target=None
        self.paused=self.pause_pending=self.audio_ready=False
        self.job=OwnerJob();environment=QProcessEnvironment.systemEnvironment()
        environment.insert(JOB_ENV,self.job.name);environment.insert('PYTHONUTF8','1')
        self.process.setProcessEnvironment(environment);self.process.setWorkingDirectory(str(ROOT))
        self.process.setProgram(str(Path(sys.executable).with_name('python.exe')))
        self.process.setArguments(['-B','-X','utf8','-m','app.web_follow.desktop'])
        self.pending_command=command;self.web_mode=True;self.running=True
        self.running_changed.emit(True);self.dirty=True;self.process.start()

    def save_credential(self,value:str,provider=None):
        provider=provider or self.translation_provider;provider_info(provider)
        if 'credential_save:'+provider in self.operations:
            message=_tr('该来源的上次保存仍在进行，请稍后重试。')
            self.credential_saved.emit(False,message);self.credential_saved_for.emit(provider,False,message);return
        def save():
            if provider=='deepseek':store_credential(value)
            else:store_credential(value,provider)
            try:return manage_credential('status') if provider=='deepseek' else manage_credential('status',provider)
            except Exception as error:
                raise CredentialStoreError('verify',getattr(error,'winerror',None)) from None
        def completed(status):
            self.credentials_ready.emit({**status,'provider':provider})
            self.credential_saved.emit(True,_tr('密钥已保存到 Windows 用户凭据。'))
            self.credential_saved_for.emit(provider,True,_tr('密钥已保存到 Windows 用户凭据。'))
        def failed(message):
            self.credential_saved.emit(False,message);self.credential_saved_for.emit(provider,False,message)
        self._task('credential_save:'+provider,save,completed,failed)

    def save_preferences(self,store,settings):
        self._task('preferences',lambda:store.save(settings),
            lambda _:self.preferences_saved.emit(settings,True),lambda _:self.preferences_saved.emit(settings,False))

    def start(self,target:ProcessInfo,language:str,translation:bool,seconds:int=3600,glossary:Path|None=None,
              translation_mode:str='preview',transcript_directory:Path|None=None,translation_model:str|None=None,target_language:str='zh'):
        if self.running:raise RuntimeError(_tr('已有正在运行的会话。'))
        self.web_mode=False;self.pending_command=None;self.web_clock={}
        if language not in ASR_LANGUAGES or not 1<=seconds<=28800:raise ValueError(_tr('语言或运行时长无效。'))
        if translation_mode not in ('preview','sentence'):raise ValueError(_tr('翻译方式无效。'))
        if target_language not in ('zh','en'):raise ValueError(_tr('翻译目标语言无效。'))
        provider_info(self.translation_provider)
        if translation_model is not None:validate_model(self.translation_provider,translation_model)
        current=ProcessSelector().inspect(target.pid)
        expected=source_executable(self.source_kind)
        if current!=target or (expected is not None and current.name.casefold()!=expected):
            raise ValueError(f"{_tr(SOURCE_LABELS[self.source_kind])}{_tr(' 进程已改变，请刷新后重新选择。')}")
        if not (ROOT/'native/build/Release/elt_capture.exe').is_file():raise FileNotFoundError(_tr('未找到音频捕获程序，请先按 README 完成构建。'))
        config=ASRConfig.load(ROOT/'config/asr.toml',language=language,course_terms='')
        if not (Path(config.model)/'model.bin').is_file():raise FileNotFoundError(_tr('未找到本地识别模型，请先按 README 准备模型。'))
        self.decoder=EventDecoder();self.model.reset();self.course.reset();self.diagnostics.clear();self.stderr_tail=''
        self.telemetry=RuntimeMetrics();self.received_ns=0
        self.paint_records.clear()
        self.process.readAllStandardOutput();self.process.readAllStandardError()
        self.stopping=self.forced=False;self.backend_pid=None
        self.paused=self.pause_pending=self.audio_ready=False
        self.job=OwnerJob()
        environment=QProcessEnvironment.systemEnvironment()
        environment.insert(JOB_ENV,self.job.name);environment.insert('PYTHONUTF8','1')
        self.process.setProcessEnvironment(environment);self.process.setWorkingDirectory(str(ROOT))
        python=Path(sys.executable).with_name('python.exe')
        self.process.setProgram(str(python))
        arguments=['-X','utf8','-m','app.ui.runner','translate-live','--pid',str(target.pid),
                   '--expected-created',str(target.created),'--source',self.source_kind,
                   '--language',language,'--seconds',str(seconds),'--translation-mode',translation_mode]
        arguments.extend(['--translation-provider',self.translation_provider])
        arguments.extend(['--target-language',target_language])
        if translation_model is not None:arguments.extend(['--translation-model',translation_model])
        if not translation:arguments.append('--source-only')
        if glossary is not None:arguments.extend(['--glossary',str(glossary)])
        if transcript_directory is not None:arguments.extend(['--transcript-directory',str(transcript_directory)])
        self.process.setArguments(arguments)
        self.capture_target=target;self.running=True;self.running_changed.emit(True);self.dirty=True
        self.process.start()

    def stop(self):
        if not self.running or self.stopping:return
        self.stopping=True
        self.pause_timer.stop();self.pause_changed.emit()
        self.process.write(b'STOP\n')
        self.stop_timer.start()
        self.event_received.emit({'event':'gui_stopping'})

    def toggle_pause(self):
        if self.web_mode:return  # The original webpage is the only video controller.
        if not self.running or self.stopping or not self.audio_ready or self.pause_pending:return
        command=b'RESUME\n' if self.paused else b'PAUSE\n'
        if self.process.write(command)!=len(command):
            self.problem.emit(_tr('暂停指令无法送达，正在停止本次会话。'));self.stop();return
        self.pause_pending=True;self.pause_timer.start();self.pause_changed.emit()

    def _pause_timeout(self):
        self.problem.emit(_tr('音频暂停或恢复未在限定时间内完成，正在停止本次会话。'))
        self.stop()

    def force_stop(self):
        if not self.running:return
        self.forced=True
        if self.job:self.job.close();self.job=None
        if self.process.state()!=QProcess.NotRunning:self.process.kill()

    def _stdout(self):
        try:
            for event in self.decoder.feed(bytes(self.process.readAllStandardOutput())):self.accept_event(event)
        except (ValueError,UnicodeError):
            self.problem.emit(_tr('后台数据异常，本次捕获正在停止。'));self.stop()

    def _stderr(self):
        data=bytes(self.process.readAllStandardError()).decode('utf-8',errors='replace')
        self.stderr_tail=(self.stderr_tail+data)[-16000:]

    def accept_event(self,event):
        name=event['event']
        if name=='web_service_ready':
            self.web_ready.emit(event['url']);return  # Pairing nonce stays out of diagnostics.
        if name=='web_clock':
            self.web_clock=event
            key=event.get('segment_id');self.model.latest=key if key in self.model.records else None
            self.dirty=True
            if event.get('skipped_windows') or event.get('source_incomplete'):self.course.incomplete=True
        if name=='audio_source_ready':self.audio_ready=True;self.pause_changed.emit()
        elif name in ('audio_capture_paused','audio_capture_resumed'):
            self.paused=name=='audio_capture_paused';self.pause_pending=False;self.pause_timer.stop();self.pause_changed.emit()
        self.telemetry.event(event)
        if ((name=='asr_summary' and event.get('complete') is False) or
                (name=='bilingual_summary' and event.get('asr_complete') is False) or
                name in ('bilingual_source_error','bilingual_error','asr_error','gui_backend_error')):
            self.course.incomplete=True
        if name=='gui_backend_started':self.backend_pid=event['pid']
        if name=='subtitle':
            if self.model.update(event):
                self.course.offer(event);self.subtitle_received.emit(event)
                self.dirty=True;self.generation+=1;self.received_ns=now_ns()
                self.paint_records[(event['session_id'],event['segment_id'])]=(self.generation,self.received_ns,
                    event['revision'],event['candidate_revision'],event.get('translated_revision'),event['state'])
                while len(self.paint_records)>128:self.paint_records.popitem(last=False)
        elif name not in ('transcript','asr_update','asr_submitted','asr_queues','gpu'):
            # Keep bounded, non-audio diagnostics; raw source and keys are not exported.
            safe={k:v for k,v in event.items() if k not in ('words','confirmed_words','candidate_words','text','config','preview_source')}
            self.diagnostics.append(safe)
        if name not in ('transcript','asr_update','subtitle','asr_submitted'):
            self.event_received.emit(event)

    def begin_paint(self,view,record,parts=('source','translation')):
        metadata=self.paint_records.get((record['session_id'],record['segment_id']))
        if not metadata or metadata[2:]!=(record['revision'],record['candidate_revision'],record.get('translated_revision'),record['state']):return None
        token,received=metadata[:2];self.telemetry.begin_paint(token,view,record,received,parts)
        return token

    def painted(self,view,part,token,when):
        event=self.telemetry.painted(token,view,part,when)
        if event:self.diagnostics.append(event)

    def _flush(self):
        if self.dirty:self.dirty=False;self.view_changed.emit()

    def _process_error(self,error):
        if error==QProcess.FailedToStart:
            self.problem.emit(_tr('后台程序无法启动，请检查项目的 Python 环境。'))
            self._finished(1,QProcess.CrashExit)

    def _finished(self,code,status):
        if not self.running:return
        self._stdout();self._stderr();self.stop_timer.stop()
        self.pause_timer.stop()
        try:self.decoder.finish()
        except ValueError:
            if not self.stopping:self.problem.emit(_tr('后台意外结束，最后一条数据未完成。'))
        if self.job:self.job.close();self.job=None
        self.telemetry.finish_usage()
        self.running=False;self._flush();self.running_changed.emit(False)
        self.audio_ready=False;self.pause_pending=False;self.paused=False;self.pause_changed.emit()
        self.finished.emit(code,self.stopping)

    def cleanup_idle(self):
        self.closed=True;self.render_timer.stop();self.pool.clear()
        if self.job:self.job.close();self.job=None
        self.pool.waitForDone(1000)
