from types import SimpleNamespace
import pytest
from app.audio.processes import (ProcessInfo,ProcessSelector,source_candidates,source_executable,
    process_source,select_process)

ROWS=[(1,0,'explorer.exe'),(10,1,'chrome.exe'),(11,10,'chrome.exe'),(12,10,'CHROME.EXE'),
      (13,11,'chrome.exe'),(20,1,'msedge.exe'),(21,20,'msedge.exe'),
      (22,20,'msedgewebview2.exe'),(30,1,'vlc.exe'),(31,30,'vlc.exe'),(40,1,'chrome.exe')]


def test_browser_discovery_selects_window_owners_and_preserves_vlc_process_selection():
    assert source_candidates(ROWS,'chrome',{10,20,40})==[10,40]
    assert source_candidates(ROWS,'edge',{10,20,40})==[20]
    assert source_candidates(ROWS,'vlc')==[30,31]
    assert source_candidates([],'chrome',set())==[]


def test_orphan_browser_children_without_windows_are_never_offered():
    rows=ROWS+[(50,999,'chrome.exe')]
    assert source_candidates(rows,'chrome',{10,40})==[10,40]
    assert source_candidates(rows,'chrome',set())==[]
    with pytest.raises(ValueError):source_candidates(rows,'chrome')


@pytest.mark.parametrize('source',['system','microphone','firefox','chrome.exe',''])
def test_only_explicit_supported_app_sources_are_accepted(source):
    with pytest.raises(ValueError):source_executable(source)
    with pytest.raises(ValueError):source_candidates(ROWS,source)


@pytest.mark.parametrize('name,source',[('VLC.EXE','vlc'),('chrome.exe','chrome'),('MSEdge.exe','edge')])
def test_process_to_native_source_identity(name,source):
    assert process_source(ProcessInfo(1,name,'C:/'+name,100))==source


def test_other_executables_use_explicit_generic_process_capture():
    for name in ('msedgewebview2.exe','evilchrome.exe','python.exe'):
        assert process_source(ProcessInfo(1,name,'C:/'+name,100))=='process'
    assert source_candidates(ROWS,'edge',{22})==[]  # Generic support does not broaden the Edge shortcut.


def test_discovery_rechecks_name_and_never_substitutes_a_browser_child():
    def inspect(pid):
        if pid==10:raise PermissionError('unavailable root')
        # A PID changed between snapshot and inspection.
        return ProcessInfo(pid,'python.exe','C:/python.exe',300)
    selector=SimpleNamespace(snapshot=lambda:ROWS,visible_window_pids=lambda:{10,40},inspect=inspect)
    found,errors=ProcessSelector.discover(selector,'chrome')
    assert found==[] and {error['pid'] for error in errors}=={10,40}
    assert not any(error['pid'] in (11,12,13) for error in errors)


def test_multiple_browser_roots_require_an_explicit_pid():
    def inspect(pid):return ProcessInfo(pid,'chrome.exe','C:/chrome.exe',100+pid)
    selector=SimpleNamespace(snapshot=lambda:ROWS,visible_window_pids=lambda:{10,40},inspect=inspect)
    found,errors=ProcessSelector.discover(selector,'chrome')
    assert not errors and len(found)==2
    with pytest.raises(ValueError):select_process(found)
    assert select_process(found,40).pid==40


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows window ownership API')
def test_visible_window_owner_reader_filters_hidden_and_disappeared_windows(monkeypatch):
    from app.audio import processes
    class Function:
        def __init__(self,function):self.function=function
        def __call__(self,*args):return self.function(*args)
    def enumerate_windows(callback,context):
        for window in (1,2,3):assert callback(window,context)
        return True
    def owner(window,pid):
        if window==3:return 0  # closed during enumeration
        pid._obj.value=42;return 1
    api=SimpleNamespace(EnumWindows=Function(enumerate_windows),IsWindowVisible=Function(lambda window:window!=2),
                        GetWindowThreadProcessId=Function(owner))
    monkeypatch.setattr(processes.ct,'WinDLL',lambda *args,**kwargs:api)
    selector=object.__new__(ProcessSelector)
    assert selector.visible_window_pids()=={42}


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows window ownership API')
def test_window_enumeration_failure_is_reported_instead_of_empty_success(monkeypatch):
    from app.audio import processes
    class Function:
        def __init__(self,function):self.function=function
        def __call__(self,*args):return self.function(*args)
    def fail(*args):processes.ct.set_last_error(5);return False
    api=SimpleNamespace(EnumWindows=Function(fail),IsWindowVisible=Function(lambda window:True),
                        GetWindowThreadProcessId=Function(lambda *args:0))
    monkeypatch.setattr(processes.ct,'WinDLL',lambda *args,**kwargs:api)
    with pytest.raises(OSError):object.__new__(ProcessSelector).visible_window_pids()
