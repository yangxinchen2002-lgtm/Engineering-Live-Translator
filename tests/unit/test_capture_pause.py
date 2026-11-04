import asyncio
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from app.asr.source import LiveSource
from app.audio.processes import ProcessInfo
from app.audio.protocol import Packet,Kind,SampleFormat,control
from app.asr.clock import now_ns


def wait_for(predicate,timeout=2):
    deadline=time.monotonic()+timeout
    while not predicate():
        if time.monotonic()>deadline:raise TimeoutError('test condition not met')
        time.sleep(.002)


def fake_capture(monkeypatch):
    from app.asr import source as module
    target=ProcessInfo(123,'player.exe','C:/player.exe',7);sessions=[]
    class Capture:
        def __init__(self,*args):
            self.started=False;self.stopped=False;self.closed=False;self.returncode=0;self.stderr='';self.sample=0
            sessions.append(self)
        def stop(self):self.stopped=True
        def close(self):self.closed=True
        def receive(self):
            if not self.started:self.started=True;return control(Kind.STATUS,0,state='started')
            if self.stopped:return control(Kind.STATUS,0,state='stopped')
            time.sleep(.002);start=self.sample;self.sample+=320
            return Packet(Kind.AUDIO,rate=16000,channels=1,format=SampleFormat.F32,frames=320,
                valid_bits=32,first_sample=start,timestamp=now_ns()//100,payload=np.ones(320,np.float32).tobytes())
    monkeypatch.setattr(module,'CaptureSession',Capture)
    monkeypatch.setattr(module,'ProcessSelector',lambda:SimpleNamespace(inspect=lambda pid:target))
    source=LiveSource(Path('helper'),target,30,2000,lambda *a,**k:None)
    return source,sessions


def test_ten_pause_resume_cycles_close_helper_and_keep_sample_axis_contiguous(monkeypatch):
    source,sessions=fake_capture(monkeypatch);source.start();frames=[]
    try:
        for index in range(10):
            wait_for(lambda:len(sessions)==index+1 and sessions[-1].sample>=640)
            source.pause_event.set();wait_for(lambda:sessions[-1].closed)
            paused=source.pause_events.get(timeout=1)
            assert paused['paused']
            queued=source.queue.qsize();time.sleep(.008)
            assert source.queue.qsize()==queued and len(sessions)==index+1
            source.pause_event.clear()
            resumed=source.pause_events.get(timeout=1)
            assert not resumed['paused'] and resumed['sample']==paused['sample']
        source.close()
        while not source.queue.empty():frames.append(source.queue.get_nowait())
        assert frames and all(left.end==right.start for left,right in zip(frames,frames[1:]))
        assert all(session.closed for session in sessions) and source.error is None
    finally:source.close()


def test_stop_while_paused_and_target_exit_while_paused_are_bounded(monkeypatch):
    from app.asr import source as module
    source,sessions=fake_capture(monkeypatch);source.start()
    try:
        wait_for(lambda:source.ready.is_set());source.pause_event.set()
        assert source.pause_events.get(timeout=1)['paused']
        def exited(pid):raise OSError('process missing')
        monkeypatch.setattr(module,'ProcessSelector',lambda:SimpleNamespace(inspect=exited))
        assert source.done.wait(1) and 'target_exited' in str(source.error)
    finally:source.close()
    source,sessions=fake_capture(monkeypatch);source.start()
    wait_for(lambda:source.ready.is_set());source.pause_event.set()
    assert source.pause_events.get(timeout=1)['paused']
    source.close();assert source.done.is_set() and source.error is None and all(s.closed for s in sessions)


def test_pause_event_overflow_is_explicit_instead_of_discarding_boundaries(monkeypatch):
    source,_=fake_capture(monkeypatch)
    for index in range(8):source._transition(index%2==0,index*320)
    with pytest.raises(BufferError,match='pause event queue overflow'):source._transition(True,2560)
    assert source.pause_events.qsize()==8


def test_pause_ends_speech_and_resets_vad_without_loading_worker_again(monkeypatch):
    from app.asr import pipeline
    from app.asr.config import ASRConfig
    from app.asr.types import InputFrame
    instances=[];submitted=[];resets=[];events=[]
    class Worker:
        def __init__(self,config):self.process=SimpleNamespace(pid=1);self.ready=True;self.busy=None;self.first=True;instances.append(self)
        def poll(self):
            if self.first:self.first=False;return {'type':'ready'}
            if self.busy:
                # Pause endpoint job's copied PCM must survive ring disposal.
                assert np.all(self.busy.audio==1);self.busy=None
            return None
        def submit(self,job):submitted.append(job);self.busy=job
        def close(self):pass
    class Vad:
        def __init__(self,config):self.position=0;self.state=SimpleNamespace(reset=lambda:None)
        def feed(self,audio):
            start=self.position;self.position+=len(audio)
            return [SimpleNamespace(kind='start',sample=start)]
        def reset_at(self,sample):self.position=sample;resets.append(sample)
    class Source:
        error=None;high_water=2
        def __init__(self):
            self.queue=queue.Queue();self.pause_events=queue.Queue();self.done=threading.Event()
            self.queue.put(InputFrame(0,np.ones(320,np.float32),now_ns()))
            self.pause_events.put({'paused':True,'sample':320})
            self.pause_events.put({'paused':False,'sample':320})
            self.queue.put(InputFrame(320,np.ones(320,np.float32),now_ns()+1_000_000_000))
            self.done.set()
        def start(self):pass
        def close(self):pass
    async def monitor(interval,emit,stop,samples):await stop.wait()
    monkeypatch.setattr(pipeline,'ASRWorker',Worker);monkeypatch.setattr(pipeline,'SileroStream',Vad)
    monkeypatch.setattr(pipeline,'gpu_monitor',monitor)
    result=asyncio.run(pipeline.run_pipeline(ASRConfig(),Source(),lambda name,**data:events.append((name,data))))
    assert result['complete'] and result['samples']==640 and len(instances)==1
    assert resets==[320,320] and [(job.start,job.end,job.endpoint) for job in submitted]==[(0,320,True),(320,640,True)]
    assert all(start>=320 for start,_,_ in submitted[1].clock_spans)
    assert submitted[1].time_at(320)>submitted[0].time_at(320)+900_000_000
    assert [name for name,_ in events if name.startswith('audio_capture_')]==['audio_capture_paused','audio_capture_resumed']


def test_vad_pause_reset_clears_context_and_pending_without_reloading_onnx():
    from app.asr.vad import SileroStream,VadState
    from app.asr.config import ASRConfig
    vad=SileroStream.__new__(SileroStream);session=object();vad.session=session
    vad.h=np.ones((1,1,128),np.float32);vad.c=vad.h.copy();vad.context=np.ones(64,np.float32)
    vad.pending=np.ones(200,np.float32);vad.position=512;vad.state=VadState(ASRConfig());vad.state.active=True
    vad.reset_at(640)
    assert vad.session is session and vad.position==640 and len(vad.pending)==0 and not vad.state.active
    assert not vad.h.any() and not vad.c.any() and not vad.context.any()


def test_gui_pause_event_is_passed_to_live_source_without_cloud(monkeypatch):
    from app.main import main
    from app.translation import cli
    pause=threading.Event();seen=[];target=SimpleNamespace(pid=42,created=100,path='app.exe')
    monkeypatch.setattr(cli,'ProcessSelector',lambda:SimpleNamespace(discover=lambda selected:([target],[])))
    monkeypatch.setattr(cli,'select_process',lambda *args:target)
    monkeypatch.setattr(cli,'LiveSource',lambda *args,**kwargs:seen.append(kwargs['pause_event']) or object())
    async def run(asr,config,source,emit,**kwargs):
        assert kwargs['client'] is None
        emit('bilingual_summary',asr_complete=True,translation_complete=False,final_subtitles=0)
    monkeypatch.setattr(cli,'run_bilingual',run)
    assert main(['translate-live','--source','sessions','--pid','42','--source-only'],pause_event=pause)==3
    assert seen==[pause]


@pytest.mark.skipif(__import__('os').name!='nt',reason='Windows stdin pipe control')
def test_real_windows_runner_control_pipe_pause_resume_stop():
    import subprocess
    import sys
    code='''import threading,time
from app.ui.runner import control
stop=threading.Event();pause=threading.Event()
thread=threading.Thread(target=control,args=(stop,pause),daemon=True);thread.start()
print('ready',flush=True)
last=False
try:
 while True:
  current=pause.is_set()
  if current!=last:print('paused' if current else 'resumed',flush=True);last=current
  time.sleep(.01)
except KeyboardInterrupt:
 stop.set();thread.join(1);print('stopped',flush=True)
'''
    child=subprocess.Popen([sys.executable,'-B','-u','-c',code],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
    messages=queue.Queue()
    reader=threading.Thread(target=lambda:[messages.put(line.strip()) for line in child.stdout],daemon=True);reader.start()
    try:
        assert messages.get(timeout=4)==b'ready'
        for command,response in ((b'PAUSE\n',b'paused'),(b'RESUME\n',b'resumed'),(b'STOP\n',b'stopped')):
            child.stdin.write(command);child.stdin.flush();assert messages.get(timeout=3)==response
        assert child.wait(timeout=3)==0
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=3)
        for stream in (child.stdin,child.stdout,child.stderr):stream.close()
