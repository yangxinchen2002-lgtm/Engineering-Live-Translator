"""Native styles must remain correct after later paints, not just on a toggle."""
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.skipif(os.name!='nt',reason='Windows layered-window input')
def test_native_overlay_input_remains_editable_after_repainting():
    pytest.importorskip('PySide6')
    script='''
import ctypes as ct
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app.ui.overlay import Overlay
app=QApplication([]);overlay=Overlay();overlay.show();app.processEvents()
api=ct.WinDLL('user32',use_last_error=True)
api.GetWindowLongPtrW.argtypes=[ct.c_void_p,ct.c_int];api.GetWindowLongPtrW.restype=ct.c_ssize_t
try:
 for enabled in (True,False,True,False):
  overlay.set_click_through(enabled)
  for index in range(3):
   overlay.repaint();QTest.qWait(15)
   style=api.GetWindowLongPtrW(int(overlay.winId()),-20)
   assert bool(style&0x20)==enabled,(enabled,style)
   assert not overlay.windowFlags()&Qt.WindowTransparentForInput
   assert not overlay.testAttribute(Qt.WA_TransparentForMouseEvents)
finally:overlay.close()
print('native overlay input toggles survive repaint')
'''
    result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[2],
        env={**os.environ,'QT_QPA_PLATFORM':'windows'},capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    assert b'native overlay input toggles survive repaint' in result.stdout
