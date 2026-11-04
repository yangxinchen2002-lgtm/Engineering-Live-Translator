from dataclasses import replace
import pytest
from app.audio.processes import ProcessInfo
from app.audio.source_volume import SourceAttenuator,process_tree

ROOT=ProcessInfo(10,'vlc.exe','C:/VLC/vlc.exe',100)


class Selector:
    def __init__(self):
        self.identities={10:ROOT,11:ProcessInfo(11,'vlc.exe',ROOT.path,101),
                         12:ProcessInfo(12,'vlc.exe',ROOT.path,90),20:ProcessInfo(20,'other.exe','C:/other.exe',105)}
    def inspect(self,pid):
        if pid not in self.identities:raise OSError('exited')
        return self.identities[pid]
    def snapshot(self):return [(10,1,'vlc.exe'),(11,10,'vlc.exe'),(12,11,'vlc.exe'),(20,1,'other.exe')]


class Session:
    def __init__(self,pid,value=.8,key=None):self.pid=pid;self.value=value;self.key=key or str(pid);self.writes=[];self.muted=True
    def get_volume(self):return self.value
    def set_volume(self,value):self.value=value;self.writes.append(value)


class Backend:
    def __init__(self,rows):self.rows=rows
    def sessions(self):return list(self.rows)


def test_only_verified_source_tree_is_attenuated_and_restored_without_compounding():
    sessions=[Session(pid) for pid in (10,11,12,20)];selector=Selector()
    controller=SourceAttenuator(ROOT,Backend(sessions),selector)
    assert set(process_tree(ROOT,selector))=={10,11}
    assert controller.update(20)==2
    assert [s.value for s in sessions]==pytest.approx([.16,.16,.8,.8])
    controller.update(20);assert len(sessions[0].writes)==1
    controller.update(40);assert sessions[0].value==pytest.approx(.32)
    assert all(s.muted for s in sessions)  # Never modify mute states.
    assert controller.restore()==0
    assert [s.value for s in sessions]==pytest.approx([.8]*4)
    assert not sessions[2].writes and not sessions[3].writes


def test_new_session_is_ducked_and_external_manual_change_is_respected():
    source=Session(10);backend=Backend([source]);controller=SourceAttenuator(ROOT,backend,Selector())
    controller.update(20);child=Session(11,.5);backend.rows.append(child)
    controller.update(20);assert child.value==pytest.approx(.1)
    source.value=.65;controller.update(20);controller.update(40)
    assert source.value==.65
    controller.restore();assert source.value==.65 and child.value==.5


def test_reopened_same_session_reuses_original_level_and_latest_control():
    first=Session(10);backend=Backend([first]);controller=SourceAttenuator(ROOT,backend,Selector())
    controller.update(20);reopened=Session(10,first.value);backend.rows=[reopened]
    controller.update(20);controller.restore()
    assert reopened.value==.8


def test_reused_root_pid_is_rejected_before_any_further_volume_change():
    source=Session(10);selector=Selector();controller=SourceAttenuator(ROOT,Backend([source]),selector)
    controller.update(20);selector.identities[10]=replace(ROOT,created=200)
    with pytest.raises(ProcessLookupError):controller.update(20)
    controller.restore();assert source.value==.8
