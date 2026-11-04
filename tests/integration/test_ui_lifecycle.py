"""Real Windows Job cleanup, independent of VLC, microphones or GPU hardware."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import pytest


@pytest.mark.skipif(os.name!='nt',reason='Windows Job Object implementation')
def test_owner_job_closes_backend_and_its_descendant():
    import win32api,win32event,win32con
    from app.ui.lifetime import OwnerJob,JOB_ENV
    root=Path(__file__).resolve().parents[2]
    owner=OwnerJob();child=None;handle=None
    script='''
import json,os,subprocess,sys,time
from app.ui.lifetime import join_owner_job,JOB_ENV
join_owner_job(os.environ[JOB_ENV])
worker=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)'],creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps({'worker_pid':worker.pid}),flush=True)
time.sleep(30)
'''
    try:
        child=subprocess.Popen([sys.executable,'-u','-c',script],cwd=root,env={**os.environ,JOB_ENV:owner.name},
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        lines=queue.Queue(maxsize=1)
        reader=threading.Thread(target=lambda:lines.put(child.stdout.readline()),daemon=True);reader.start()
        line=lines.get(timeout=10)
        assert line, 'backend could not join its GUI owner job'
        pid=json.loads(line)['worker_pid']
        handle=win32api.OpenProcess(win32con.SYNCHRONIZE|win32con.PROCESS_TERMINATE,False,pid)
        owner.close()
        child.wait(timeout=5)
        assert win32event.WaitForSingleObject(handle,5000)==win32event.WAIT_OBJECT_0
    finally:
        owner.close()
        if child is not None:
            if child.poll() is None:child.kill();child.wait(timeout=5)
            child.stdout.close();child.stderr.close()
        if handle is not None:
            if win32event.WaitForSingleObject(handle,0)!=win32event.WAIT_OBJECT_0:win32api.TerminateProcess(handle,1)
            handle.Close()
