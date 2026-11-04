"""Regression coverage for cmd.exe parsing and visible startup failures."""
from pathlib import Path
import os
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[2]


def test_command_file_is_ascii_with_windows_line_endings():
    data=(ROOT/'启动ELT.cmd').read_bytes()
    data.decode('ascii')
    assert data.count(b'\r\n')==data.count(b'\n')>0
    assert not data.startswith(b'\xef\xbb\xbf')


@pytest.mark.skipif(os.name!='nt',reason='real Windows cmd.exe parser')
def test_missing_environment_has_readable_error_from_another_working_directory(tmp_path):
    launcher=tmp_path/'launcher'
    launcher.mkdir()
    shutil.copyfile(ROOT/'启动ELT.cmd',launcher/'启动ELT.cmd')
    working=tmp_path/'another directory'
    working.mkdir()
    result=subprocess.run([os.environ.get('COMSPEC','cmd.exe'),'/d','/c',r'..\launcher\启动ELT.cmd'],
        cwd=working,input=b'\n',stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==1
    assert b'ELT could not find its Python environment.' in result.stdout
    assert b'not recognized' not in result.stdout+result.stderr
