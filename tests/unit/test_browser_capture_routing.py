from types import SimpleNamespace
import pytest
from app.audio import capture
from app.audio.processes import ProcessInfo


@pytest.mark.parametrize('name,source',[('chrome.exe','chrome'),('msedge.exe','edge'),('vlc.exe','vlc'),('firefox.exe','process'),('game.exe','process')])
def test_capture_session_passes_source_and_process_identity(monkeypatch,tmp_path,name,source):
    helper=tmp_path/'helper.exe';helper.touch()
    target=ProcessInfo(42,name,'C:/apps/'+name,1234)
    monkeypatch.setattr(capture,'ProcessSelector',lambda:SimpleNamespace(inspect=lambda pid:target))
    calls=[]
    child=SimpleNamespace(returncode=0,communicate=lambda **kwargs:(None,b''))
    monkeypatch.setattr(capture.subprocess,'Popen',lambda args,**kwargs:(calls.append(args),child)[1])
    class Pipe:
        def __init__(self,name):self.name=name
        def send(self,packet):pass
        def close(self):pass
    monkeypatch.setattr(capture,'NamedPipe',Pipe)
    with capture.CaptureSession(helper,target):pass
    args=calls[0]
    assert args[args.index('--source')+1]==source
    assert args[args.index('--pid')+1]=='42' and args[args.index('--created')+1]=='1234'


def test_changed_identity_is_rejected_before_helper_launch(monkeypatch,tmp_path):
    helper=tmp_path/'helper.exe';helper.touch()
    target=ProcessInfo(42,'chrome.exe','C:/chrome.exe',100)
    monkeypatch.setattr(capture,'ProcessSelector',lambda:SimpleNamespace(inspect=lambda pid:
        ProcessInfo(42,'chrome.exe','C:/chrome.exe',200)))
    def forbidden(*args,**kwargs):pytest.fail('stale browser PID was captured')
    monkeypatch.setattr(capture.subprocess,'Popen',forbidden)
    with pytest.raises(RuntimeError,match='identity changed'):capture.CaptureSession(helper,target)
