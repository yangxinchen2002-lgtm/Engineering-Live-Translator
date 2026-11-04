"""Two registered Windows shortcuts; no hooks, polling or keyboard recording."""
import ctypes as ct
from ctypes import wintypes as wt
import os
from PySide6.QtCore import QAbstractNativeEventFilter


class GlobalHotkeys(QAbstractNativeEventFilter):
    KEYS={1:('toggle',ord('S')),2:('edit',ord('E'))}

    def __init__(self,app,window,callback):
        super().__init__();self.app=app;self.window=int(window);self.callback=callback
        self.registered=set();self.errors={};self.api=None;self.closed=False
        if os.name!='nt':self.errors['platform']='unsupported';return
        self.api=ct.WinDLL('user32',use_last_error=True)
        self.api.RegisterHotKey.argtypes=[wt.HWND,ct.c_int,wt.UINT,wt.UINT];self.api.RegisterHotKey.restype=wt.BOOL
        self.api.UnregisterHotKey.argtypes=[wt.HWND,ct.c_int];self.api.UnregisterHotKey.restype=wt.BOOL
        for identifier,(name,key) in self.KEYS.items():
            if self.api.RegisterHotKey(self.window,identifier,0x0002|0x0001|0x4000,key):self.registered.add(identifier)
            else:self.errors[name]=ct.get_last_error()
        self.app.installNativeEventFilter(self)

    def dispatch(self,window,message,identifier):
        if not self.closed and window==self.window and message==0x0312 and identifier in self.registered:
            self.callback(self.KEYS[identifier][0]);return True
        return False

    def nativeEventFilter(self,eventType,message):
        if bytes(eventType) not in (b'windows_generic_MSG',b'windows_dispatcher_MSG'):return False,0
        msg=wt.MSG.from_address(int(message))
        return self.dispatch(msg.hWnd,msg.message,msg.wParam),0

    def close(self):
        if self.closed:return
        self.closed=True
        if self.api:
            self.app.removeNativeEventFilter(self)
            for identifier in self.registered:
                if not self.api.UnregisterHotKey(self.window,identifier):self.errors['unregister_'+str(identifier)]=ct.get_last_error()
        self.registered.clear()
