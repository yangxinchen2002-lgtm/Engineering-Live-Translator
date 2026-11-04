import asyncio
from types import SimpleNamespace
import numpy as np
import pytest
from app.asr.config import ASRConfig
from app.asr.source import AudioSource
from app.asr.types import InputFrame


def test_audio_receiver_overflow_has_separate_terminal_error():
    class Source(AudioSource):
        def _produce(self):
            for i in range(3):self._offer(InputFrame(i*320,np.zeros(320,np.float32),0))
    source=Source(2,lambda *a,**k:None)
    source.start()
    assert source.done.wait(2)
    assert isinstance(source.error,BufferError)
    assert source.queue.qsize()==2
    source.close()


def setup_pipeline(monkeypatch):
    from app.asr import pipeline
    closed=[]
    class Worker:
        def __init__(self,config):self.process=SimpleNamespace(pid=123);self.ready=False;self.busy=None
        def poll(self):return None
        def close(self):closed.append('worker')
    class Source:
        def close(self):closed.append('source')
    async def monitor(interval,emit,stop,samples):await stop.wait()
    monkeypatch.setattr(pipeline,'ASRWorker',Worker)
    monkeypatch.setattr(pipeline,'SileroStream',lambda config:None)
    monkeypatch.setattr(pipeline,'gpu_monitor',monitor)
    return pipeline,Source(),closed


def test_model_initialization_timeout_cleans_process(monkeypatch):
    pipeline,source,closed=setup_pipeline(monkeypatch)
    cfg=ASRConfig(startup_timeout_seconds=.03)
    with pytest.raises(TimeoutError):
        asyncio.run(pipeline.run_pipeline(cfg,source,lambda *a,**k:None))
    assert closed==['source','worker']


def test_cancellation_cleans_process(monkeypatch):
    pipeline,source,closed=setup_pipeline(monkeypatch)
    async def cancel():
        task=asyncio.create_task(pipeline.run_pipeline(ASRConfig(),source,lambda *a,**k:None))
        await asyncio.sleep(.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(cancel())
    assert closed==['source','worker']


def test_inference_timeout_is_explicit_and_cleans_worker(monkeypatch):
    import queue
    import threading
    import time
    pipeline,source,closed=setup_pipeline(monkeypatch)
    class BusyWorker:
        def __init__(self,config):
            self.process=SimpleNamespace(pid=123);self.ready=True
            self.busy=SimpleNamespace(id=7,submitted_ns=time.perf_counter_ns()-1_000_000_000)
            self.first=True
        def poll(self):
            if self.first:self.first=False;return {'type':'ready'}
            return None
        def close(self):closed.append('worker')
    source.error=None;source.queue=queue.Queue();source.done=threading.Event()
    source.start=lambda:None
    monkeypatch.setattr(pipeline,'ASRWorker',BusyWorker)
    events=[]
    with pytest.raises(TimeoutError):
        asyncio.run(pipeline.run_pipeline(ASRConfig(inference_timeout_seconds=.01),source,
                                         lambda event,**data:events.append((event,data))))
    assert closed==['source','worker']
    assert any(event=='asr_timeout' for event,_ in events)
