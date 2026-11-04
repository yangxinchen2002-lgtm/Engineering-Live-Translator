import json
import os
import subprocess
import sys
from pathlib import Path
import pytest


@pytest.mark.skipif(os.name!='nt',reason='Windows native shortcut bridge')
def test_qt_native_hotkey_message_is_consumed_once_and_registration_is_released():
    pytest.importorskip('PySide6')
    script='''
import ctypes as ct,json
from ctypes import wintypes as wt
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtCore import QTimer
from app.ui.hotkeys import GlobalHotkeys
app=QApplication([]);window=QWidget();window.show();calls=[]
keys=GlobalHotkeys(app,window.winId(),calls.append)
api=ct.WinDLL('user32',use_last_error=True)
api.PostMessageW.argtypes=[wt.HWND,wt.UINT,wt.WPARAM,wt.LPARAM];api.PostMessageW.restype=wt.BOOL
registered=sorted(keys.registered)
for index,identifier in enumerate(registered):
 QTimer.singleShot(100+index*100,lambda key=identifier:api.PostMessageW(int(window.winId()),0x0312,key,0))
QTimer.singleShot(450,app.quit)
try:app.exec()
finally:keys.close();window.close()
print(json.dumps({'registered':registered,'calls':calls,'errors':keys.errors,'released':not keys.registered}))
'''
    result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[2],
        env={**os.environ,'QT_QPA_PLATFORM':'windows'},capture_output=True,timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    data=json.loads(result.stdout)
    if not data['registered']:pytest.skip('shortcut combinations currently owned by another application')
    assert len(data['calls'])==len(data['registered']) and data['released']
