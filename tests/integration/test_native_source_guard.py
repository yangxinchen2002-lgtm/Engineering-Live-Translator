"""Actual helper rejects source mismatches before IPC or audio activation."""
import os
from pathlib import Path
import subprocess
import uuid
import pytest

HELPER=Path(__file__).resolve().parents[2]/'native/build/Release/elt_capture.exe'
pytestmark=pytest.mark.skipif(os.name!='nt' or not HELPER.is_file(),reason='built Windows capture helper required')


@pytest.mark.parametrize('source',['chrome','edge','vlc'])
def test_native_rejects_python_process_as_selected_audio_source(source):
    result=subprocess.run([str(HELPER),'--pipe',r'\\.\pipe\ELT-'+uuid.uuid4().hex,'--pid',str(os.getpid()),
        '--created','1','--source',source],capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==1
    assert b'target_executable_does_not_match_selected_source' in result.stderr


def test_native_rejects_system_capture_source():
    result=subprocess.run([str(HELPER),'--pipe',r'\\.\pipe\ELT-'+uuid.uuid4().hex,'--pid',str(os.getpid()),
        '--created','1','--source','system'],capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==1 and b'unsupported_audio_source' in result.stderr


def test_generic_process_still_rejects_wrong_creation_time_before_audio_activation():
    from app.audio.transport import NamedPipe
    from app.audio.protocol import control,Kind
    name=r'\\.\pipe\ELT-'+uuid.uuid4().hex
    child=subprocess.Popen([str(HELPER),'--pipe',name,'--pid',str(os.getpid()),'--created','1','--source','process'],
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    pipe=None
    try:
        pipe=NamedPipe(name);pipe.send(control(Kind.START,0))
        packet=pipe.receive()
        assert packet.kind==Kind.ERROR and 'target_identity_changed' in str(packet.json())
    finally:
        if pipe:pipe.close()
        try:child.communicate(timeout=5)
        except subprocess.TimeoutExpired:child.kill();child.communicate(timeout=3)
    assert child.returncode==1
