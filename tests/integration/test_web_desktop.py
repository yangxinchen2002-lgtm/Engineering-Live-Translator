"""Real GUI-owned service/HTTP lifecycle. No GPU, course media or cloud requests."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from urllib.parse import urlsplit
import httpx
import pytest
from app.ui.lifetime import OwnerJob,JOB_ENV

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.skipif(os.name!='nt',reason='Windows Job Object')
def test_desktop_service_uses_authoritative_settings_and_stops_cleanly():
    owner=OwnerJob();child=None;lines=queue.Queue(maxsize=256)
    try:
        child=subprocess.Popen([sys.executable,'-B','-m','app.web_follow.desktop'],cwd=ROOT,
            env={**os.environ,JOB_ENV:owner.name,'PYTHONUTF8':'1'},stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        thread=threading.Thread(target=lambda:[lines.put(json.loads(line)) for line in iter(child.stdout.readline,b'')],daemon=True);thread.start()
        config=dict(language='en',provider='deepseek',model='deepseek-flash',translate=False,narrate=False,voice=0,seconds=60,
                    duck_source=True,source_percent=25)
        child.stdin.write(b'CONFIG '+json.dumps(config).encode()+b'\n');child.stdin.flush()
        seen=[]
        while True:
            row=lines.get(timeout=15);seen.append(row)
            if row['event']=='web_service_ready':break
            assert row['event']!='gui_backend_error'
        u=urlsplit(row['url']);origin=f'{u.scheme}://{u.netloc}'
        with httpx.Client(base_url=origin,headers={'X-ELT-Lab-Token':u.fragment},trust_env=False,timeout=5) as c:
            assert '翻译、语言和朗读设置来自 ELT 主程序' in c.get('/').text
            state=c.get('/api/state').json();assert state['status']=='idle' and state['worker_pid'] is None
            assert state['playback']['duck_source'] and state['playback']['source_percent']==25
            result=c.post('/api/playback',json={'source_percent':45,'duck_source':False})
            assert result.status_code==200 and result.json()['playback']['source_percent']==45
            assert result.json()['worker_pid'] is None
            ext='a'*32
            auth={'Origin':'chrome-extension://'+ext,'X-ELT-Extension-Id':ext}
            paired=c.post('/bridge/pair',headers=auth,json={'options':{'language':'de','translate':True}})
            assert paired.status_code==200
            assert paired.json()['options']['language']=='en' and paired.json()['options']['translate'] is False
            bridge={**auth,'X-ELT-Bridge-Token':paired.json()['token']}
            child.stdin.write(b'STOP\n');child.stdin.flush()
            import time
            deadline=time.monotonic()+3;stopped=False
            while time.monotonic()<deadline:
                try:
                    result=c.post('/bridge/clock',headers=bridge,json={'owner':'test-owner'})
                    if result.json().get('stopped'):stopped=True;break
                except httpx.HTTPError:break
                time.sleep(.03)
            assert stopped
        child.wait(timeout=10);assert child.returncode==0
        assert not any(r['event']=='audio_source_ready' for r in seen)
    finally:
        owner.close()
        if child:
            if child.poll() is None:child.kill();child.wait(timeout=5)
            for stream in (child.stdin,child.stdout,child.stderr):
                try:stream.close()
                except OSError:pass


@pytest.mark.skipif(os.name!='nt',reason='Windows recognizer lease')
def test_recognizer_lease_excludes_another_process_and_releases():
    from app.asr.lease import ASRLease
    script='''
from app.asr.lease import ASRLease
lease=ASRLease()
try:
 lease.acquire();print('free')
except ValueError:print('busy')
finally:lease.close()
'''
    lease=ASRLease().acquire()
    try:
        result=subprocess.run([sys.executable,'-B','-c',script],cwd=ROOT,capture_output=True,text=True,timeout=10,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode==0 and result.stdout.strip()=='busy'
    finally:lease.close()
    result=subprocess.run([sys.executable,'-B','-c',script],cwd=ROOT,capture_output=True,text=True,timeout=10,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0 and result.stdout.strip()=='free'
