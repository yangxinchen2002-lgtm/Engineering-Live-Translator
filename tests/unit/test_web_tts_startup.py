import base64
import io
from pathlib import Path
import queue
import threading
import time
from types import SimpleNamespace as NS
import wave

import pytest
from app.web_follow import tts
from app.web_follow.timeline import Cue


def test_cold_model_finishes_loading_after_first_cue_expires_without_reloading(monkeypatch,tmp_path):
    entered=threading.Event();release=threading.Event();generated=threading.Event();instances=[];events=[];spoken=[]
    clock=NS(value=0)
    class Client:
        def __init__(self,options,status):instances.append(self);self.status=status;self.closed=False
        def wait_ready(self,cancelled):
            entered.set()
            while not release.wait(.01):
                if cancelled():raise InterruptedError()
            self.status(status='ready',engine='qwen',device='cuda',model='1.7B',pid=123)
        def synthesize(self,text,path,stale,cancelled):spoken.append(text);generated.set();return 1.
        def close(self):self.closed=True
    monkeypatch.setattr(tts,'QwenFiles',Client)
    stream=tts.SpeechQueue(tts.settings({}),tmp_path,NS(value=1),lambda kind,**kw:events.append((kind,kw)),clock)
    try:
        assert entered.wait(1)
        stream.offer(1,Cue('first',0,2,'first source',translation='过期句'))
        clock.value=3
        stream.offer(1,Cue('next',10,15,'next source',translation='应朗读的句子'))
        release.set();assert generated.wait(2);stream.queue.join()
        assert len(instances)==1 and not instances[0].closed and spoken==['应朗读的句子']
        assert [row['pid'] for kind,row in events if kind=='tts_status' and row.get('status')=='ready']==[123,123]
    finally:release.set();stream.close()
    assert instances[0].closed


def test_stop_cancels_initial_model_loading_and_reaps_the_client(monkeypatch,tmp_path):
    entered=threading.Event();closed=threading.Event()
    class Client:
        def __init__(self,*a):pass
        def wait_ready(self,cancelled):
            entered.set()
            while not cancelled():time.sleep(.01)
            raise InterruptedError()
        def close(self):closed.set()
    monkeypatch.setattr(tts,'QwenFiles',Client)
    stream=tts.SpeechQueue(tts.settings({}),tmp_path,NS(value=1),lambda *a,**k:None)
    assert entered.wait(1);stream.close()
    assert closed.is_set() and not stream.thread.is_alive()


def bare_client():
    client=tts.QwenFiles.__new__(tts.QwenFiles);client.ready=True;client.closed=threading.Event()
    client.events=queue.Queue();client.serial=0;client.options={'tts_voice':'serena'}
    client.process=NS(stdin=io.BytesIO());return client


def audio_event(identity,value):
    return dict(event='speech_audio',id=identity,rate=24000,
                pcm=base64.b64encode(int(value).to_bytes(2,'little',signed=True)*100).decode())


def test_expired_generation_is_drained_and_the_next_request_reuses_the_warm_model(tmp_path):
    client=bare_client();client.events.put(audio_event('1',50));client.events.put(dict(event='speech_done',id='1'))
    calls=0
    def expires_during_audio():
        nonlocal calls
        calls+=1;return calls>=3
    with pytest.raises(tts.CueExpired):client.synthesize('过期句',tmp_path/'old.wav',expires_during_audio)
    assert client.ready and client.events.empty() and not (tmp_path/'old.wav').exists()
    assert not (tmp_path/'old.part').exists()
    client.events.put(audio_event('2',200));client.events.put(dict(event='speech_done',id='2'))
    duration=client.synthesize('当前句',tmp_path/'current.wav',lambda:False)
    with wave.open(str(tmp_path/'current.wav'),'rb') as wav:
        assert wav.getnframes()==100 and wav.readframes(1)==(200).to_bytes(2,'little',signed=True)
    assert duration==pytest.approx(100/24000)


def test_stop_aborts_draining_and_does_not_wait_for_a_late_done(tmp_path):
    client=bare_client()
    with pytest.raises(InterruptedError):client.synthesize('测试',tmp_path/'stopped.wav',lambda:False,lambda:True)
    assert not (tmp_path/'stopped.wav').exists() and not (tmp_path/'stopped.part').exists()
