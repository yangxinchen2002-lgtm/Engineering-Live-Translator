import json
from pathlib import Path
from types import SimpleNamespace as NS
import threading
import time
import pytest
from app.web_follow.player import Player,observation,service_address
from app.web_follow.server import Lab,options_from
from app.web_follow.timeline import Cue
from app.web_follow import tts


def test_only_local_authenticated_service_and_supported_frame_are_accepted():
    assert service_address('http://127.0.0.1:1234/#'+'a'*40)==('http://127.0.0.1:1234','a'*40)
    for url in ('https://example.com/#'+'a'*40,'http://127.0.0.1:1234/#short','http://user@127.0.0.1:1234/#'+'a'*40):
        with pytest.raises(ValueError):service_address(url)
    value=dict(page='https://video.opencast.tum.de/paella8/x',source='https://video.opencast.tum.de/a.mp4',
               position=10,paused=False,seek=False,rate=1,area=100)
    assert observation(value)['position']==10
    with pytest.raises(ValueError):observation({**value,'page':'https://evil.example'})
    with pytest.raises(ValueError):observation({**value,'rate':float('nan')})


def test_qwen_options_are_strict_and_system_remains_backward_compatible():
    assert options_from({})['speech_engine']=='system'
    options=options_from(dict(speech_engine='qwen',tts_model='1.7B',tts_voice='aiden'))
    assert options['tts_model']=='1.7B' and options['tts_voice']=='aiden'
    for key,value in [('speech_engine','remote'),('tts_model','7B'),('tts_voice','invented'),('tts_device','auto')]:
        with pytest.raises(ValueError):options_from({key:value})


def test_late_speech_updates_survive_batch_commit_without_replacing_source():
    lab=Lab()
    try:
        cue=Cue('a',0,2,'source',translation='中文')
        from dataclasses import asdict
        lab.preview={'a':asdict(cue)}
        lab.apply_speech({**asdict(cue),'speech':'a.wav','speech_seconds':1})
        merged=lab.speech_result(cue)
        assert merged.speech=='a.wav' and merged.source=='source'
        lab.timeline.cues=[merged];lab.preview.clear()
        lab.apply_speech({**asdict(cue),'translation':'wrong revision','speech':'wrong.wav'})
        assert lab.timeline.cues[0].speech=='a.wav'
        lab.apply_speech({**asdict(cue),'speech':'a.wav','speech_error':'test failure'})
        assert lab.timeline.cues[0].source=='source' and lab.timeline.cues[0].speech_error=='test failure'
    finally:lab.close()


def test_qwen_generation_is_bounded_and_does_not_block_the_subtitle_producer(monkeypatch,tmp_path):
    entered=threading.Event();release=threading.Event();events=[]
    class Client:
        def __init__(self,*a):pass
        def wait_ready(self,cancelled):pass
        def synthesize(self,text,path,stale,cancelled):entered.set();release.wait(2);return 1.
        def close(self):pass
    monkeypatch.setattr(tts,'QwenFiles',Client)
    stream=tts.SpeechQueue(tts.settings({}),tmp_path,NS(value=1),lambda kind,**kw:events.append((kind,kw)))
    try:
        cue=Cue('first',0,2,'source',translation='中文')
        stream.offer(1,cue);assert entered.wait(1)
        for index in range(9):stream.offer(1,Cue(f'queued-{index}',3+index,5+index,'source',translation='中文'))
        assert stream.queue.qsize()==8
        assert any('队列已满' in row['cue']['speech_error'] for kind,row in events if kind=='speech_cue')
    finally:release.set();stream.close()


def test_expired_sentence_is_never_sent_to_local_tts(monkeypatch,tmp_path):
    generated=[]
    class Client:
        def __init__(self,*a):pass
        def wait_ready(self,cancelled):pass
        def synthesize(self,*a):generated.append(True);return 1
        def close(self):pass
    monkeypatch.setattr(tts,'QwenFiles',Client)
    stream=tts.SpeechQueue(tts.settings({}),tmp_path,NS(value=2),lambda *a,**kw:None,NS(value=10))
    try:
        stream.offer(1,Cue('old-generation',0,2,'source',translation='中文'))
        stream.offer(2,Cue('old-clock',0,2,'source',translation='中文'))
        stream.queue.join();assert not generated
    finally:stream.close()


def test_repeated_tts_failures_stop_reloading_and_keep_subtitles(monkeypatch,tmp_path):
    attempts=[];events=[]
    class Client:
        def __init__(self,*a):pass
        def wait_ready(self,cancelled):pass
        def synthesize(self,*a):attempts.append(True);raise RuntimeError('test-only')
        def close(self):pass
    monkeypatch.setattr(tts,'QwenFiles',Client)
    stream=tts.SpeechQueue(tts.settings({}),tmp_path,NS(value=1),lambda kind,**kw:events.append((kind,kw)))
    try:
        cue=Cue('a',0,2,'source remains',translation='中文')
        for _ in range(3):stream.offer(1,cue);stream.queue.join()
        assert stream.disabled and len(attempts)==3
        stream.offer(1,cue)
        assert len(attempts)==3 and events[-1][1]['cue']['source']=='source remains'
        assert '连续失败' in events[-1][1]['cue']['speech_error']
    finally:stream.close()


def test_internal_observer_keeps_original_playback_clock_read_only():
    source=(Path(__file__).resolve().parents[2]/'app/web_follow/web/player-observer.js').read_text(encoding='utf-8')
    import re
    assert not re.search(r'video\.(?:pause|play)\s*\(|video\.(?:currentTime|playbackRate|volume|muted)\s*=(?!=)',source)
    assert 'ELTFollow.Narrator' in source and 'pending.clear()' in source
    volume=(Path(__file__).resolve().parents[2]/'app/web_follow/extension/source-volume.js').read_text(encoding='utf-8')
    assert not re.search(r'video\.(?:pause|play)\s*\(|video\.(?:currentTime|playbackRate|muted)\s*=(?!=)',volume)


def test_main_gui_connect_starts_following_navigation_preserves_it_and_stop_stays_stopped(monkeypatch):
    class Client:
        def __init__(self,**kw):pass
        def request(self,*a,**kw):return NS(raise_for_status=lambda:None,json=lambda:{'defaults':{}})
        def close(self):pass
    monkeypatch.setattr('httpx.Client',Client)
    player=Player(NS());player.notice=lambda text:None;player.execute=lambda *a,**kw:None
    thread=threading.Thread(target=player.loop);thread.start()
    def wait(predicate):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if predicate():return
            time.sleep(.01)
        raise AssertionError('player command not applied')
    try:
        player.enqueue('CONNECT',url='http://127.0.0.1:1234/#'+'a'*40);wait(lambda:player.following)
        player.frames['old']=(0,None,{'source':''})
        player.enqueue('NAVIGATE');wait(lambda:not player.frames)
        assert player.following
        player.enqueue('STOP');wait(lambda:not player.following)
        player.frames['old']=(0,None,{'source':''})
        player.enqueue('NAVIGATE');wait(lambda:not player.frames)
        assert not player.following
    finally:player.exit.set();thread.join(3);assert not thread.is_alive()
