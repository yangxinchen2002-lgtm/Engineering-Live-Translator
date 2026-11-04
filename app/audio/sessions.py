"""Read-only mixer discovery. No COM objects escape the discovery apartment."""
from dataclasses import replace
import os
import traceback
from .processes import ProcessInfo


def excluded_tree(rows, pid, selector):
    excluded={pid};identities={}
    try:identities[pid]=selector.inspect(pid)
    except OSError:return excluded
    for _ in range(len(rows)):
        added=set()
        for child,parent,_ in rows:
            if parent not in identities or child in excluded:continue
            try:
                identity=selector.inspect(child)
                if identity.created<identities[parent].created or selector.inspect(parent)!=identities[parent]:continue
                identities[child]=identity;added.add(child)
            except OSError:continue
        if not added:break
        excluded.update(added)
    return excluded


def application_process(process, selector, parents, windows):
    """Use a window-owning same-image ancestor for browser audio helpers.

    A headless session keeps its exact owner. Never merge unrelated headless
    Python programs merely because their interpreter path happens to match.
    """
    original=process;visited={process.pid}
    for _ in range(32):
        if process.pid in windows:return process
        parent=parents.get(process.pid)
        if not parent or parent in visited:break
        visited.add(parent)
        try:ancestor=selector.inspect(parent)
        except OSError:break
        if ancestor.created>process.created or ancestor.path.casefold()!=process.path.casefold():break
        process=ancestor
    return original


def application_name(process, session_name=''):
    try:
        import win32api
        translations=win32api.GetFileVersionInfo(process.path,'\\VarFileInfo\\Translation')
        for language,codepage in translations[:8]:
            value=win32api.GetFileVersionInfo(process.path,f'\\StringFileInfo\\{language:04x}{codepage:04x}\\FileDescription')
            if isinstance(value,str) and value.strip():return value.strip()[:120]
    except Exception:
        pass  # Optional PE description; exact executable identity remains available.
    if isinstance(session_name,str) and session_name.strip() and not session_name.startswith('@'):
        return ' '.join(session_name.split())[:120]
    return process.name


def collect_audio_sources(selector, backend, *, owner_pid=None, name_resolver=application_name):
    """Return only primitive process metadata, with bounded discovery diagnostics."""
    rows=selector.snapshot();parents={pid:parent for pid,parent,_ in rows}
    excluded=excluded_tree(rows,os.getpid() if owner_pid is None else owner_pid,selector)
    windows=selector.visible_window_pids();groups={};errors=[]
    for session in backend.sessions():
        if session.pid<=0 or session.pid in excluded:continue
        try:
            owner=selector.inspect(session.pid)
            target=application_process(owner,selector,parents,windows)
            if target.pid in excluded:continue
            if selector.inspect(session.pid)!=owner or selector.inspect(target.pid)!=target:
                raise ProcessLookupError('audio source identity changed during discovery')
            key=(target.pid,target.created,target.path)
            if key not in groups:
                if len(groups)>=128:raise BufferError('audio source list exceeds 128 applications')
                groups[key]=replace(target,display_name=name_resolver(target,getattr(session,'display_name','')),
                    audio_state='inactive',audio_sessions=0)
            current=groups[key]
            groups[key]=replace(current,audio_sessions=current.audio_sessions+1,
                audio_state='active' if getattr(session,'state',0)==1 or current.audio_state=='active' else 'inactive')
        except OSError:
            if len(errors)<64:errors.append({'pid':session.pid,'error':'audio_source_exited_or_inaccessible'})
    errors.extend(getattr(backend,'errors',[])[:max(0,64-len(errors))])
    return sorted(groups.values(),key=lambda p:(p.audio_state!='active',p.display_name.casefold(),p.pid)),errors


def _discover_in_apartment(selector):
    from .source_volume import CoreAudioBackend
    # All backend/control/volume wrappers die on returning from this function,
    # before the outer CoUninitialize. Only ProcessInfo values cross threads.
    return collect_audio_sources(selector,CoreAudioBackend())


def discover_audio_sources(selector):
    import pythoncom
    initialized=False
    try:
        try:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED);initialized=True
        except pythoncom.com_error as error:
            if error.hresult!=-2147417850:raise  # Existing apartment, RPC_E_CHANGED_MODE.
        return _discover_in_apartment(selector)
    except BaseException as error:
        # Unwound traceback frames can otherwise retain controls until after
        # CoUninitialize. Release their locals while the apartment is alive.
        pending=[error];seen=set()
        while pending:
            current=pending.pop()
            if id(current) in seen:continue
            seen.add(id(current));traceback.clear_frames(current.__traceback__)
            pending.extend(value for value in (current.__cause__,current.__context__) if value is not None)
        raise
    finally:
        if initialized:pythoncom.CoUninitialize()
