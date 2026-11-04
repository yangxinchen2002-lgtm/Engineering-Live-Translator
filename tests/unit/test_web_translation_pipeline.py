import asyncio
from dataclasses import asdict,replace
from datetime import datetime,timezone
import queue
import threading
import time
from types import SimpleNamespace as NS
import pytest
from app.web_follow.server import Lab
from app.web_follow.timeline import Cue
from app.web_follow import worker,translation
from app.web_follow.player import player_frames


def test_asr_commits_two_source_windows_while_first_translation_is_still_waiting(monkeypatch,tmp_path):
    pytest.importorskip('faster_whisper')
    import faster_whisper
    released=threading.Event();entered=threading.Event();batches=threading.Event();translated=threading.Event()
    rows=[];tasks=queue.Queue();errors=[]
    class Output:
        def put(self,value,timeout=None):
            rows.append(value)
            if sum(r['type']=='batch' for r in rows)>=2:batches.set()
            if sum(r['type']=='cue' and bool(r['cue']['translation']) for r in rows)>=2:translated.set()
    class Model:
        def __init__(self,*a,**kw):pass
        def transcribe(self,*a,**kw):return [NS(words=[NS(start=1,end=2,word='A complete sentence.')])],NS(language='en')
    class Lease:
        def acquire(self):pass
        def close(self):pass
    monkeypatch.setattr(faster_whisper,'WhisperModel',Model)
    monkeypatch.setattr('app.asr.lease.ASRLease',Lease)
    monkeypatch.setattr('app.asr.worker.configure_gpu_runtime',lambda:None)
    monkeypatch.setattr('app.asr.config.ASRConfig.load',lambda *a,**kw:NS(device='cpu',model='test-only',compute_type='float32'))
    monkeypatch.setattr(worker,'probe',lambda source:{'duration':100})
    monkeypatch.setattr(worker,'decode_window',lambda *a,**kw:([],{}))
    async def blocked(cues,language,options,context,ledger,stale,on_result):
        entered.set()
        while not released.is_set():
            if stale():raise InterruptedError()
            await asyncio.sleep(.01)
        for cue in cues:on_result(replace(cue,translation='测试译文'))
    monkeypatch.setattr(translation,'translate_cues',blocked)
    def run():
        try:worker.worker_main(NS(hls=False),dict(language='en',model='deepseek-flash',provider='deepseek',
            translate=True,narrate=False,voice=0),tasks,Output(),NS(value=1),str(tmp_path))
        except BaseException as error:errors.append(error)
    thread=threading.Thread(target=run);thread.start()
    try:
        tasks.put((1,0,6));tasks.put((1,6,12))
        assert batches.wait(3) and entered.wait(1)
        assert not released.is_set() and not any(r['type']=='cue' for r in rows)
        assert [r['end'] for r in rows if r['type']=='batch']==[6,12]
        released.set();assert translated.wait(2)
    finally:released.set();tasks.put(None);thread.join(5)
    assert not thread.is_alive() and not errors


def test_late_translation_survives_next_batch_and_does_not_replace_another_source():
    lab=Lab()
    try:
        a=Cue('a',1,2,'First.',asr_confirmed=True);b=Cue('b',8,9,'Second.',asr_confirmed=True)
        lab.timeline.commit(1,0,6,[a]);lab.timeline.commit(1,6,12,[b]);lab.preview.clear()
        lab.apply_cue(asdict(replace(a,translation='第一句。')))
        assert lab.timeline.cues[0].translation=='第一句。' and lab.timeline.cues[1].source=='Second.'
        lab.apply_cue(asdict(replace(a,source='Wrong sentence',translation='错误')))
        assert lab.timeline.cues[0].translation=='第一句。'
        lab.preview={'b':asdict(replace(b,translation='第二句。'))}
        assert lab.speech_result(b).translation=='第二句。'
    finally:lab.close()


def test_usage_from_an_older_asr_snapshot_never_rolls_back_newer_network_usage():
    lab=Lab()
    try:
        lab.update_usage({'usage_revision':2,'token_usage':{'total_tokens':20}})
        lab.update_usage({'usage_revision':1,'token_usage':{'total_tokens':10}})
        assert lab.metrics['usage']['usage_revision']==2
    finally:lab.close()


def test_error_state_is_not_erased_by_continuing_video_or_seek_messages():
    lab=Lab()
    try:
        lab.source=NS();lab.status='error';lab.error='original useful error';lab.generation=NS(value=1)
        lab.clock(dict(position=100,rate=1,paused=False,seek=True))
        assert lab.status=='error' and lab.error=='original useful error' and lab.generation.value==1
    finally:lab.source=None;lab.close()


def test_source_and_translation_prepared_horizons_are_reported_separately():
    lab=Lab()
    try:
        lab.options={'translate':True};lab.timeline.position=3
        lab.timeline.commit(1,0,15,[Cue('a',5,7,'First.',translation='已译',asr_confirmed=True),
                                  Cue('b',8,10,'Second.',asr_confirmed=True)])
        state=lab.state()
        assert state['source_ahead_seconds']==12 and state['translation_ahead_seconds']==5
    finally:lab.close()


def test_dual_picture_uses_soundtrack_clock_while_rendering_on_largest_picture():
    camera=('camera',(1,None,dict(area=100,position=102.5,audible=True,audio_decoded=True)))
    slides=('slides',(1,None,dict(area=900,position=100,audible=False,audio_decoded=False)))
    clock,display=player_frames([slides,camera])
    assert clock[0]=='camera' and clock[1][2]['position']==102.5 and display[0]=='slides'
    camera[1][2]['audible']=False
    assert player_frames([slides,camera],'camera')[0][0]=='camera'


def test_hls_seven_sample_timestamp_jitter_is_repaired_but_real_gaps_and_edges_fail():
    import numpy as np
    from app.web_follow.media import repair_rounding,HLS_TIMESTAMP_HOLE_LIMIT
    audio=np.arange(320000,dtype=np.float32);covered=np.ones(audio.size,dtype=bool)
    covered[10000:10007]=False;audio[~covered]=0
    with pytest.raises(ValueError):repair_rounding(audio,covered)
    result=repair_rounding(audio,covered,max_hole_samples=HLS_TIMESTAMP_HOLE_LIMIT)
    assert result['rounding_repaired_samples']==7 and result['largest_gap_samples']==7
    assert audio[10003]==10003
    covered[20000:20009]=False
    with pytest.raises(ValueError):repair_rounding(audio,covered,max_hole_samples=HLS_TIMESTAMP_HOLE_LIMIT)
    covered[:]=True;covered[:7]=False
    with pytest.raises(ValueError):repair_rounding(audio,covered,max_hole_samples=HLS_TIMESTAMP_HOLE_LIMIT)


def test_hls_timestamp_repairs_have_a_strict_cumulative_budget():
    import numpy as np
    from app.web_follow.media import repair_rounding,HLS_TIMESTAMP_HOLE_LIMIT
    audio=np.ones(16000,dtype=np.float32);covered=np.ones(audio.size,dtype=bool)
    for index in (10,100,1000):covered[index]=False
    with pytest.raises(ValueError):repair_rounding(audio,covered,max_hole_samples=HLS_TIMESTAMP_HOLE_LIMIT)
