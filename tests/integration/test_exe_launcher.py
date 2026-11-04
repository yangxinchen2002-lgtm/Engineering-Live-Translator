"""Actual GUI-subsystem executable checks; no speech capture or cloud calls."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[2]
EXE=ROOT/'ELT.exe'
pytestmark=pytest.mark.skipif(os.name!='nt' or not EXE.is_file(),reason='build the Windows ELT.exe launcher first')


def test_launcher_is_a_real_windows_gui_executable():
    data=EXE.read_bytes();pe=struct.unpack_from('<I',data,0x3c)[0]
    assert data[:2]==b'MZ' and data[pe:pe+4]==b'PE\0\0'
    assert struct.unpack_from('<H',data,pe+4)[0]==0x8664
    assert struct.unpack_from('<H',data,pe+24+68)[0]==2


@pytest.mark.parametrize('case',['runtime_missing','invalid_portable_profile','metadata_too_large','unknown_argument'])
def test_launcher_reports_bad_installation_without_falling_back_or_opening_a_console(tmp_path,case):
    exe=tmp_path/'ELT.exe';shutil.copy2(EXE,exe)
    if case=='invalid_portable_profile':(tmp_path/'distribution.json').write_text('{"profile":"../other-user"}')
    elif case=='metadata_too_large':(tmp_path/'distribution.json').write_text('x'*16385)
    arguments=['--quiet']+(['--unknown'] if case=='unknown_argument' else [])
    result=subprocess.run([str(exe),*arguments],timeout=10)
    assert result.returncode==1


def test_exe_reopens_english_interface_from_isolated_preferences(tmp_path):
    import json
    from app.ui.preferences import UISettings,PreferencesStore
    store=PreferencesStore(tmp_path/'ELT/ui-settings.json')
    store.save(UISettings(ui_language='en',target_language='en'))
    report=tmp_path/'startup.json'
    result=subprocess.run([str(EXE),'--quiet','--check','--report',str(report)],cwd=ROOT,
        env={**os.environ,'LOCALAPPDATA':str(tmp_path),'QT_QPA_PLATFORM':'offscreen'},timeout=30)
    assert result.returncode==0
    data=json.loads(report.read_text('utf-8'))
    assert data['ui_language']=='en' and data['window_visible'] and not data['capture_running']
