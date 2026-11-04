import base64
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from app.speech.buffering import required_audio_reserve
from app.speech.config import SpeechConfig
from app.ui.speech import SpeechController
from tests.unit.test_speech_pipeline import Process
from tests.unit.test_speech_and_course_notes import record


def test_slow_generation_reserve_covers_the_projected_playback_shortfall():
    duration=10.56;generation=9.4772456;speed=1.6
    reserve=required_audio_reserve(2.56,2.56*generation/duration,37,speed)
    # Remaining generation must finish before this utterance would finish playing.
    assert (duration-reserve)*generation/duration<duration/speed
    assert reserve>3 and reserve<duration


def test_fast_generation_only_needs_a_small_audio_reserve():
    assert required_audio_reserve(1.28,.6,160,1.6)==pytest.approx(1.92)
    assert required_audio_reserve(0,0,160,1.25)==pytest.approx(1.5)


def test_recent_slow_generation_and_chunk_jitter_protect_a_fast_looking_start():
    usual=required_audio_reserve(1.28,.6,40,1.6)
    slow=required_audio_reserve(1.28,.6,40,1.6,recent_rtf=.9)
    jittery=required_audio_reserve(1.28,.6,40,1.6,jitter_seconds=2)
    assert slow>usual and jittery>=3.2


def test_complete_text_is_submitted_immediately_but_audio_waits_for_a_reserve(monkeypatch):
    app=QApplication.instance() or QApplication([]);clock=[0]
    monkeypatch.setattr('app.ui.speech.now_ns',lambda:clock[0])
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True,speed=1.6,auto_catch_up=False)
    speech.active=True;speech.ready=True;speech.process=Process()
    text='这是一段需要连续播放的讲解。'*4
    speech.offer(record(0,translated=text))
    assert [r['text'] for r in speech.process.commands]==[text]
    audio=base64.b64encode(b'\x01\x00'*15360).decode()
    clock[0]=600_000_000;speech._event({'event':'speech_audio','id':'1','rate':24000,'pcm':audio})
    assert not speech._audio_ready() and speech.current['raw_bytes']==30720
    # A short completed utterance never waits for an unattainable reserve.
    speech._event({'event':'speech_done','id':'1'})
    assert speech._audio_ready() and speech.current['raw_bytes']==30720
    speech.close();app.processEvents()


def test_unexpected_starvation_waits_for_this_utterance_to_finish_and_stop_clears_it(monkeypatch):
    from collections import deque
    from PySide6.QtMultimedia import QAudio
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr('app.ui.speech.now_ns',lambda:2_000_000_000)
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True)
    events=[];speech.diagnostic.connect(events.append)
    class Sink:
        def error(self):return QAudio.Error.UnderrunError
        def state(self):return QAudio.State.IdleState
        def processedUSecs(self):return 1_000_000
        def stop(self):pass
        def deleteLater(self):pass
    speech.sink=Sink();speech.audio=object();speech.rendered_samples=24000
    speech.current={'id':'1','raw':deque(),'raw_bytes':0,'samples':24000,'rate':24000,'done':False,
                    'playing':True,'text':'这句还在生成。','submitted_ns':0}
    speech.generating_id='1';speech._tick()
    assert speech.refill_started_ns is not None
    assert [row['event'] for row in events]==['speech_audio_underrun']
    payload=base64.b64encode(b'\x01\x00'*15360).decode()
    speech._event({'event':'speech_audio','id':'1','rate':24000,'pcm':payload})
    speech._tick();speech._tick()
    assert speech.current['raw_bytes']==30720 and len(events)==1
    speech._event({'event':'speech_done','id':'1'});speech._tick()
    assert speech.refill_started_ns is None and any(row['event']=='speech_audio_refilled' for row in events)
    assert speech.current['raw_bytes']==30720  # No conversion or loss without a converter.
    speech.stop();assert speech.refill_started_ns is None and speech.current is None
    speech.close();app.processEvents()
