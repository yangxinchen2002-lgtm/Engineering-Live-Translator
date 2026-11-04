"""Windows process identity = PID + creation FILETIME + executable path."""
from __future__ import annotations

import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import dataclass, field
import os

SOURCE_EXECUTABLES = {'vlc': 'vlc.exe', 'chrome': 'chrome.exe', 'edge': 'msedge.exe', 'sessions': None}
SOURCE_LABELS = {'vlc': 'VLC', 'chrome': 'Chrome', 'edge': 'Edge', 'sessions': 'Windows 应用音频'}


def source_executable(source: str) -> str | None:
    try:return SOURCE_EXECUTABLES[source]
    except KeyError:raise ValueError('unsupported audio source; choose vlc, chrome, edge or sessions') from None


def process_source(process: ProcessInfo) -> str:
    if process.pid<=0 or process.created<=0 or not process.path or not process.name:
        raise ValueError('invalid capture process identity')
    for source, executable in SOURCE_EXECUTABLES.items():
        if process.name.casefold() == executable:return source
    return 'process'  # An explicitly selected Windows audio-session application.


def source_candidates(rows: list[tuple[int, int, str]], source: str,
                      window_pids: set[int] | None = None) -> list[int]:
    """Browser targets must own a visible top-level window, not just share a name.

    This excludes orphaned renderers/utility processes after the browser exits.
    Only process/window-owner IDs and executable names are read, not page titles,
    URLs or command lines. VLC keeps its original headless-capture support.
    """
    executable = source_executable(source)
    if source=='sessions':raise ValueError('application discovery requires Windows audio sessions')
    if source!='vlc' and window_pids is None:
        raise ValueError('browser discovery requires top-level window ownership')
    return sorted(pid for pid, _, name in rows if name.casefold() == executable
                  and (source == 'vlc' or pid in window_pids))


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    path: str
    created: int
    display_name: str = field(default='', compare=False)
    audio_state: str = field(default='', compare=False)
    audio_sessions: int = field(default=0, compare=False)


def select_process(processes: list[ProcessInfo], pid: int | None = None) -> ProcessInfo:
    matches = [p for p in processes if pid is None or p.pid == pid]
    if not matches:
        raise ValueError("audio source not found (or PID inaccessible); open the selected app and refresh")
    if len(matches) != 1:
        raise ValueError("multiple audio source processes; choose explicitly with --pid")
    return matches[0]


def identity_changes(previous: list[ProcessInfo], current: list[ProcessInfo]) -> dict:
    old = {(p.pid, p.created): p for p in previous}
    new = {(p.pid, p.created): p for p in current}
    return {"exited": [old[k] for k in old.keys() - new.keys()],
            "started": [new[k] for k in new.keys() - old.keys()]}


class ProcessSelector:
    def __init__(self):
        if os.name != "nt":
            raise OSError("process selection requires Windows")
        self.k32 = ct.WinDLL("kernel32", use_last_error=True)
        class Entry(ct.Structure):
            _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                        ("th32DefaultHeapID", ct.c_size_t), ("th32ModuleID", wt.DWORD),
                        ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                        ("pcPriClassBase", wt.LONG), ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]
        self.Entry = Entry
        signatures = {
            "CreateToolhelp32Snapshot": ([wt.DWORD, wt.DWORD], wt.HANDLE),
            "Process32FirstW": ([wt.HANDLE, ct.POINTER(Entry)], wt.BOOL),
            "Process32NextW": ([wt.HANDLE, ct.POINTER(Entry)], wt.BOOL),
            "OpenProcess": ([wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
            "CloseHandle": ([wt.HANDLE], wt.BOOL),
            "QueryFullProcessImageNameW": ([wt.HANDLE, wt.DWORD, wt.LPWSTR, ct.POINTER(wt.DWORD)], wt.BOOL),
            "GetProcessTimes": ([wt.HANDLE] + [ct.POINTER(wt.FILETIME)] * 4, wt.BOOL),
        }
        for name, (args, result) in signatures.items():
            f = getattr(self.k32, name)
            f.argtypes, f.restype = args, result

    def inspect(self, pid: int) -> ProcessInfo:
        handle = self.k32.OpenProcess(0x1000, False, pid)
        if not handle:
            raise ct.WinError(ct.get_last_error())
        try:
            path, size = ct.create_unicode_buffer(32768), wt.DWORD(32768)
            if not self.k32.QueryFullProcessImageNameW(handle, 0, path, ct.byref(size)):
                raise ct.WinError(ct.get_last_error())
            times = [wt.FILETIME() for _ in range(4)]
            if not self.k32.GetProcessTimes(handle, *(ct.byref(t) for t in times)):
                raise ct.WinError(ct.get_last_error())
            return ProcessInfo(pid, os.path.basename(path.value), path.value,
                               times[0].dwLowDateTime | times[0].dwHighDateTime << 32)
        finally:
            self.k32.CloseHandle(handle)

    def snapshot(self) -> list[tuple[int, int, str]]:
        snapshot = self.k32.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ct.c_void_p(-1).value:
            raise ct.WinError(ct.get_last_error())
        rows = []
        try:
            entry = self.Entry()
            entry.dwSize = ct.sizeof(entry)
            ok = self.k32.Process32FirstW(snapshot, ct.byref(entry))
            while ok:
                rows.append((entry.th32ProcessID, entry.th32ParentProcessID, entry.szExeFile))
                ok = self.k32.Process32NextW(snapshot, ct.byref(entry))
            error = ct.get_last_error()
            if error != 18:  # ERROR_NO_MORE_FILES
                raise ct.WinError(error)
        finally:
            self.k32.CloseHandle(snapshot)
        return rows

    def visible_window_pids(self) -> set[int]:
        """Read desktop window ownership only; no text extraction or UI control."""
        user32=ct.WinDLL('user32',use_last_error=True)
        callback_type=ct.WINFUNCTYPE(wt.BOOL,wt.HWND,wt.LPARAM)
        user32.EnumWindows.argtypes=[callback_type,wt.LPARAM];user32.EnumWindows.restype=wt.BOOL
        user32.IsWindowVisible.argtypes=[wt.HWND];user32.IsWindowVisible.restype=wt.BOOL
        user32.GetWindowThreadProcessId.argtypes=[wt.HWND,ct.POINTER(wt.DWORD)]
        user32.GetWindowThreadProcessId.restype=wt.DWORD
        pids=set();failures=[]
        @callback_type
        def visit(window,context):
            try:
                if user32.IsWindowVisible(window):
                    pid=wt.DWORD()
                    # A window may close between enumeration and this lookup.
                    if user32.GetWindowThreadProcessId(window,ct.byref(pid)) and pid.value:pids.add(pid.value)
                return True
            except BaseException as error:
                failures.append(error);return False
        ct.set_last_error(0)
        success=user32.EnumWindows(visit,0)
        if failures:raise failures[0]
        if not success:
            code=ct.get_last_error()
            if code:raise ct.WinError(code)
            raise RuntimeError('browser window enumeration failed without a Windows error code')
        return pids

    def discover(self, source: str = 'vlc') -> tuple[list[ProcessInfo], list[dict]]:
        executable = source_executable(source)
        if source=='sessions':
            from .sessions import discover_audio_sources
            return discover_audio_sources(self)
        rows = self.snapshot()
        windows=self.visible_window_pids() if source!='vlc' else None
        result, errors = [], []
        for pid in source_candidates(rows, source, windows):
            try:
                process = self.inspect(pid)
                if process.name.casefold() != executable:
                    errors.append({'pid': pid, 'error': 'process changed during discovery'})
                    continue
                result.append(process)
            except OSError as error:
                errors.append({'pid': pid, 'error': str(error)})
        return sorted(result, key=lambda process: process.pid), errors
