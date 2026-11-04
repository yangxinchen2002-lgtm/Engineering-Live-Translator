"""Small independent guardian; Qt shutdown never force-kills volume restoration."""
from app.i18n import tr as _tr
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
from PySide6.QtCore import QObject,Signal,QTimer
from app.asr.config import ROOT
from .lifetime import JOB_ENV


class SourceVolumeController(QObject):
    status_changed=Signal(str)
    diagnostic=Signal(dict)

    def __init__(self,parent=None):
        super().__init__(parent);self.process=None;self.desired=None;self.failed=None;self.buffer=b'';self.reported_error=False;self.stopping=False
        self.timer=QTimer(self);self.timer.setInterval(200);self.timer.timeout.connect(self._poll);self.timer.start()

    def set_target(self,target,percent=20):
        if type(percent) is not int or not 0<=percent<=100:raise ValueError('invalid source volume percentage')
        desired=(target,percent) if target is not None and percent<100 else None
        if desired==self.desired:return
        self.desired=desired;self.failed=None
        if desired is None:
            self._stop();return
        if self.process is not None and self.process.poll() is None:
            if not self.stopping:self._send(target,percent)
            return
        if self.process is not None:self._dispose()
        env=os.environ.copy();env.pop(JOB_ENV,None);env['PYTHONUTF8']='1'
        try:
            self.process=subprocess.Popen([str(Path(sys.executable).with_name('python.exe')),'-X','utf8','-u',
                '-m','app.audio.volume_guardian','--owner',str(os.getpid())],cwd=ROOT,env=env,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
            self.buffer=b'';self.reported_error=False;self._send(target,percent)
            self.status_changed.emit(_tr('原声：正在调整所选音源…'))
        except OSError:self._error()

    def _send(self,target,percent):
        try:
            data=json.dumps({'command':'set','target':asdict(target),'percent':percent},ensure_ascii=False)+'\n'
            self.process.stdin.write(data.encode('utf-8'));self.process.stdin.flush()
        except (OSError,ValueError):self._error()

    def _error(self):
        self.failed=self.desired;self.reported_error=True
        self.status_changed.emit(_tr('原声音量暂时无法自动调整，朗读和字幕继续。'))

    def _poll(self):
        if self.process is None:return
        try:
            import msvcrt,win32file,win32pipe
            import pywintypes
            handle=msvcrt.get_osfhandle(self.process.stdout.fileno())
            _,available,_=win32pipe.PeekNamedPipe(handle,0)
            if available:
                _,data=win32file.ReadFile(handle,min(available,32768));self.buffer+=data
            if len(self.buffer)>32768:raise ValueError('oversized volume output')
            while b'\n' in self.buffer:
                line,self.buffer=self.buffer.split(b'\n',1);row=json.loads(line);self.diagnostic.emit(row)
                event=row['event']
                if event=='source_volume_applied':self.status_changed.emit(f"{_tr('原声：保留原音量的 ')}{row['percent']}%")
                elif event=='source_volume_waiting':self.status_changed.emit(_tr('原声：等待所选音源开始发声…'))
                elif event=='source_volume_restored':self.status_changed.emit(_tr('原声音量已恢复'))
                elif event=='source_volume_source_ended':
                    self.failed=self.desired;self.status_changed.emit(_tr('音源已退出或改变，已结束原声调整'))
                elif event=='source_volume_busy':self.status_changed.emit(_tr('原声已由另一 ELT 窗口管理'))
                elif event in ('source_volume_error','source_volume_restore_warning'):self._error()
        except (OSError,ValueError,KeyError,pywintypes.error):pass  # Broken stdout is normal during a clean exit.
        if self.process.poll() is not None:
            if self.process.returncode and not self.reported_error:self._error()
            self._dispose()
            if self.desired is not None and self.failed!=self.desired:
                desired=self.desired;self.desired=None;self.set_target(*desired)

    def _stop(self):
        if self.process is None:return
        if self.process.poll() is not None:self._poll();return
        self.stopping=True
        try:
            self.process.stdin.write(b'{"command":"stop"}\n');self.process.stdin.flush();self.process.stdin.close()
            self.process.wait(timeout=1.5)
        except (OSError,ValueError,subprocess.TimeoutExpired):
            # Keep the guardian alive: EOF/owner death still restores its leases.
            # Popen destruction closes handles but does not kill this process.
            pass
        if self.process.poll() is not None:
            self._poll()
            if not self.reported_error:self.status_changed.emit(_tr('原声音量已恢复'))

    def _dispose(self):
        if self.process:
            for stream in (self.process.stdin,self.process.stdout):
                if stream and not stream.closed:stream.close()
        self.process=None;self.buffer=b'';self.stopping=False

    def close(self):
        self.timer.stop();self.desired=None;self._stop()
