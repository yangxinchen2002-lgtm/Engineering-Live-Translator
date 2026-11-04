"""Own a separate visible browser test profile; never reuse or close user windows.

This host does not capture audio or automate browser UI. Play the test page manually
or through the supported Computer Use tools, then run the normal ELT CLI/GUI.
Create OUTPUT/stop.request to close ONLY this test browser. A deadline also cleans up.
"""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.audio.processes import ProcessSelector
from app.ui.lifetime import OwnerJob


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',choices=('chrome','edge'),required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-seconds',type=int,default=600)
    args=parser.parse_args()
    if not 30<=args.max_seconds<=900:parser.error('max-seconds must be 30..900')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    paths=([Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe',
            Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe'] if args.source=='chrome' else
           [Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
            Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe'])
    executable=next((path for path in paths if path.is_file()),None)
    if executable is None:raise FileNotFoundError('supported installed browser was not found')
    profile=ROOT/'.tmp/browser-fixtures'/uuid.uuid4().hex;profile.mkdir(parents=True)
    job=OwnerJob();child=None
    with (output/'browser.stderr.txt').open('xb') as error:
        try:
            child=subprocess.Popen([str(executable),'--user-data-dir='+str(profile),
                '--no-first-run','--no-default-browser-check','--new-window',
                (ROOT/'tools/browser_audio_check.html').as_uri()],stdout=subprocess.DEVNULL,stderr=error,
                creationflags=subprocess.CREATE_NO_WINDOW)
            import win32api,win32job,win32con
            handle=win32api.OpenProcess(win32con.PROCESS_SET_QUOTA|win32con.PROCESS_TERMINATE,False,child.pid)
            try:win32job.AssignProcessToJobObject(job.handle,handle)
            finally:handle.Close()
            deadline=time.monotonic()+20;target=None
            while time.monotonic()<deadline and child.poll() is None:
                found,_=ProcessSelector().discover(args.source)
                target=next((process for process in found if process.pid==child.pid),None)
                if target:break
                time.sleep(.1)
            if target is None:raise RuntimeError('test browser did not expose its own visible window')
            data={**asdict(target),'source':args.source,'profile':str(profile),'test_fixture_only':True}
            (output/'browser.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'test_browser_ready':data},ensure_ascii=False),flush=True)
            deadline=time.monotonic()+args.max_seconds
            while child.poll() is None and time.monotonic()<deadline and not (output/'stop.request').exists():
                time.sleep(.1)
        finally:
            job.close()
            if child is not None:
                try:child.wait(timeout=5)
                except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
            (output/'host-stopped.json').write_text(json.dumps({'test_browser_stopped':True}),encoding='utf-8')
    return 0


if __name__=='__main__':raise SystemExit(main())
