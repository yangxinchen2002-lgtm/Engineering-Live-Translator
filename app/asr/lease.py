"""One ELT recognizer per Windows session; the OS releases it after a crash."""
from app.i18n import tr as _tr
import os


class ASRLease:
    def __init__(self):self.handle=None;self.owned=False

    def acquire(self):
        if os.name!='nt':raise OSError('ELT desktop recognition requires Windows')
        import win32event
        self.handle=win32event.CreateMutex(None,False,'Local\\ELT.Recognizer.V1')
        result=win32event.WaitForSingleObject(self.handle,0)
        if result not in (win32event.WAIT_OBJECT_0,win32event.WAIT_ABANDONED):
            self.close()
            raise ValueError(_tr('另一个 ELT 识别会话正在运行，请先停止后再开始。'))
        self.owned=True
        return self

    def close(self):
        if self.handle is not None:
            if self.owned:
                import win32event
                win32event.ReleaseMutex(self.handle);self.owned=False
            self.handle.Close();self.handle=None
