"""Real ten-cycle capture and process HANDLE check; requires an already playing VLC."""
import argparse
import ctypes as ct
from ctypes import wintypes as wt
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.audio.capture import CaptureSession
from app.audio.processes import ProcessSelector
from app.audio.protocol import Kind


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    k32 = ct.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.GetProcessHandleCount.argtypes = [wt.HANDLE, ct.POINTER(wt.DWORD)]
    def handles(h):
        n = wt.DWORD()
        if not k32.GetProcessHandleCount(h, ct.byref(n)):
            raise ct.WinError(ct.get_last_error())
        return n.value
    parent = k32.GetCurrentProcess()
    target = ProcessSelector().inspect(args.pid)
    retained_sessions = []
    rows = []
    baseline = handles(parent)
    for cycle in range(1, 11):
        s = CaptureSession(ROOT / "native/build/Release/elt_capture.exe", target)
        helper_pid = s.child.pid
        child_handles = handles(int(s.child._handle))
        started = time.monotonic()
        stopped = False
        frames = 0
        max_queue = 0
        try:
            while True:
                if not stopped and time.monotonic() - started >= 1:
                    s.stop()
                    stopped = True
                p = s.receive()
                if p.kind == Kind.AUDIO:
                    frames += p.frames
                else:
                    info = p.json()
                    if p.kind == Kind.ERROR:
                        raise RuntimeError(info)
                    max_queue = max(max_queue, info.get("queue_packets", 0))
                    if info.get("state") == "stopped": break
        finally:
            s.close()
        retained_sessions.append(s)
        rows.append({"cycle": cycle, "helper_pid": helper_pid, "helper_exit": s.returncode,
                     "helper_active_handles": child_handles, "parent_handles_after_close": handles(parent),
                     "frames": frames, "max_queue": max_queue})
    result = {"baseline_parent_handles": baseline, "cycles": rows,
              "retained_closed_sessions": len(retained_sessions),
              "all_helpers_exited": all(r["helper_exit"] == 0 for r in rows),
              "parent_handle_growth": rows[-1]["parent_handles_after_close"] - rows[0]["parent_handles_after_close"]}
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, indent=2)
    print(json.dumps(result))


if __name__ == "__main__": main()
