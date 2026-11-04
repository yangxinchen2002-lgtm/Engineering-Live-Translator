from dataclasses import replace
from types import SimpleNamespace
import pytest
from app.audio.processes import ProcessInfo
from app.audio.sessions import collect_audio_sources,application_process


def selector(processes,parents=None,windows=()):
    identities={p.pid:p for p in processes}
    def inspect(pid):
        if pid not in identities:raise ProcessLookupError('exited')
        return identities[pid]
    return SimpleNamespace(inspect=inspect,visible_window_pids=lambda:set(windows),
        snapshot=lambda:[(p.pid,(parents or {}).get(p.pid,1),p.name) for p in processes])


def session(pid,state=1):return SimpleNamespace(pid=pid,state=state,display_name='Player')
def backend(*sessions):return SimpleNamespace(sessions=lambda:list(sessions),errors=[])


def test_mixer_groups_sessions_per_application_and_reuses_browser_window_root():
    chrome=ProcessInfo(10,'chrome.exe','C:/chrome.exe',10)
    child=ProcessInfo(11,'chrome.exe',chrome.path,11)
    game=ProcessInfo(20,'game.exe','C:/game.exe',20)
    s=selector([chrome,child,game],{11:10},windows={10,20})
    found,errors=collect_audio_sources(s,backend(session(11),session(10,0),session(20,0)),owner_pid=999,
        name_resolver=lambda p,n:p.name)
    assert not errors and [p.pid for p in found]==[10,20]
    assert found[0].audio_state=='active' and found[0].audio_sessions==2
    assert found[1].audio_state=='inactive'
    assert found[0]==chrome and replace(found[0],display_name='Changed name')==chrome


def test_headless_interpreters_are_separate_and_elt_tree_and_system_sounds_are_excluded():
    entries=[ProcessInfo(pid,'python.exe','C:/python.exe',pid) for pid in (30,31,32,40,41)]
    s=selector(entries,{31:30,32:30,41:40})
    found,errors=collect_audio_sources(s,backend(*(session(pid) for pid in (0,31,32,40,41))),owner_pid=40,
        name_resolver=lambda p,n:p.name)
    assert not errors and {p.pid for p in found}=={31,32}


def test_pid_reuse_and_disappeared_sessions_never_become_capture_targets():
    p=ProcessInfo(10,'player.exe','C:/player.exe',10)
    s=selector([p],windows={10});calls=[0]
    def inspect(pid):
        if pid!=10:raise ProcessLookupError('not found')
        calls[0]+=1
        return p if calls[0]==1 else replace(p,created=99)
    s.inspect=inspect
    found,errors=collect_audio_sources(s,backend(session(10)),owner_pid=999)
    assert not found and errors[0]['error']=='audio_source_exited_or_inaccessible'
    found,errors=collect_audio_sources(selector([]),backend(session(80)),owner_pid=999)
    assert not found and errors[0]['pid']==80


def test_parent_creation_time_prevents_reused_pid_ancestry():
    child=ProcessInfo(11,'chrome.exe','C:/chrome.exe',10)
    parent=replace(child,pid=10,created=100)
    assert application_process(child,selector([child,parent]),{11:10},{10})==child


def test_reused_elt_pid_does_not_hide_unrelated_older_audio_process():
    elt=ProcessInfo(40,'pythonw.exe','C:/ELT/pythonw.exe',100)
    unrelated=ProcessInfo(41,'player.exe','C:/player.exe',50)
    actual_child=ProcessInfo(42,'python.exe','C:/ELT/python.exe',110)
    s=selector([elt,unrelated,actual_child],{41:40,42:40},windows={41})
    found,errors=collect_audio_sources(s,backend(session(41),session(42)),owner_pid=40,
        name_resolver=lambda p,n:p.name)
    assert not errors and [p.pid for p in found]==[41]


def test_discovery_capacity_is_explicit_instead_of_unbounded_or_silent_drop():
    processes=[ProcessInfo(pid,'player.exe','C:/player.exe',pid) for pid in range(10,139)]
    s=selector(processes,windows={p.pid for p in processes})
    with pytest.raises(BufferError,match='128'):
        collect_audio_sources(s,backend(*(session(p.pid) for p in processes)),owner_pid=999,
            name_resolver=lambda p,n:p.name)


def test_discovery_com_apartment_is_released_on_failure(monkeypatch):
    import sys
    from app.audio import sessions
    calls=[]
    fake=SimpleNamespace(COINIT_APARTMENTTHREADED=2,CoInitializeEx=lambda mode:calls.append('init'),
        CoUninitialize=lambda:calls.append('release'),com_error=OSError)
    monkeypatch.setitem(sys.modules,'pythoncom',fake)
    class ApartmentResource:
        def __del__(self):calls.append('resource_released')
    def fail(s):
        resource=ApartmentResource()
        raise RuntimeError('discovery failed')
    monkeypatch.setattr(sessions,'_discover_in_apartment',fail)
    with pytest.raises(RuntimeError):sessions.discover_audio_sources(None)
    assert calls==['init','resource_released','release']
