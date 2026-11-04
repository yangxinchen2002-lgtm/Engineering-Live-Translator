"""Opt-in real Windows WebView2 lifecycle; only the local welcome page is opened."""
import importlib.util
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import pytest
from app.ui.lifetime import OwnerJob,JOB_ENV


@pytest.mark.hardware
@pytest.mark.skipif(os.name!='nt' or os.environ.get('ELT_REAL_PLAYER_TEST')!='1',reason='explicit real WebView2 window opt-in required')
def test_internal_player_joins_formal_job_and_closes_without_orphans():
    pytest.importorskip('webview');import psutil
    job=OwnerJob();child=None;events=queue.Queue();descendants=[]
    try:
        child=subprocess.Popen([sys.executable,'-B','-X','utf8','-m','app.web_follow.player'],
            cwd=Path(__file__).resolve().parents[2],env={**os.environ,JOB_ENV:job.name},
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        def reader():
            for raw in child.stdout:
                try:events.put(json.loads(raw))
                except ValueError:pass
        threading.Thread(target=reader,daemon=True).start()
        child.stdin.write(b'{"command":"CONFIG","url":""}\n');child.stdin.flush()
        assert events.get(timeout=35)['event']=='player_ready'
        descendants=psutil.Process(child.pid).children(recursive=True)
        assert descendants
        child.stdin.write(b'{"command":"CLOSE"}\n');child.stdin.flush()
        child.wait(timeout=15);assert child.returncode==0,child.stderr.read().decode('utf-8','replace')[-2000:]
    finally:
        job.close()
        if child:
            if child.poll() is None:child.wait(timeout=5)
            for stream in (child.stdin,child.stdout,child.stderr):stream.close()
    import time
    limit=time.monotonic()+5
    while any(p.is_running() for p in descendants) and time.monotonic()<limit:time.sleep(.1)
    assert not any(p.is_running() for p in descendants)
