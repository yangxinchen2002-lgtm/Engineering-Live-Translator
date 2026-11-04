"""Regression coverage for immediate, separate delivery of short translations."""
import base64
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from app.speech.config import SpeechConfig,split_for_speech
from app.ui.speech import SpeechController
from tests.unit.test_speech_pipeline import Process
from tests.unit.test_speech_and_course_notes import record


@pytest.mark.parametrize('device',['cpu','cuda'])
def test_short_translations_submit_immediately_and_prefetch_separately(monkeypatch,device):
    app=QApplication.instance() or QApplication([]);clock=[0]
    monkeypatch.setattr('app.ui.speech.now_ns',lambda:clock[0])
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True,device=device)
    speech.active=True;speech.ready=True;speech.process=Process();events=[]
    speech.diagnostic.connect(events.append)
    texts=['请注意，','这里有一个条件。','Check the matrix.']
    for index,text in enumerate(texts):
        speech.offer(record(index,translated=text));clock[0]+=100_000_000
    assert [r['text'] for r in speech.process.commands]==texts[:1]
    assert speech.current['submitted_ns']==speech.current['queued_ns']==0
    speech._event({'event':'speech_done','id':'1'})
    assert speech.prefetched[0]['text']==texts[1]
    assert [r['text'] for r in speech.process.commands]==texts[:2]
    speech._event({'event':'speech_done','id':'2'})
    speech.current=None;speech._next()
    assert speech.current['text']==texts[1] and speech.prefetched[0]['text']==texts[2]
    assert [r['text'] for r in speech.process.commands]==texts
    assert all(r['source_parts']==1 for r in events if r['event']=='speech_utterance_submitted')
    speech.close();app.processEvents()


def test_immediate_short_text_still_waits_for_the_audio_reserve():
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True)
    speech.active=True;speech.ready=True;speech.process=Process()
    speech.offer(record(0,translated='请注意，'))
    assert speech.process.commands[0]['text']=='请注意，'
    audio=base64.b64encode(b'\x01\x00'*15360).decode()
    speech._event({'event':'speech_audio','id':'1','rate':24000,'pcm':audio})
    assert not speech._audio_ready() and speech.sink is None
    speech._event({'event':'speech_done','id':'1'})
    assert speech._audio_ready()
    speech.finish_input();assert len(speech.process.commands)==1
    speech.close();app.processEvents()


@pytest.mark.parametrize('device,limit',[('cpu',60),('cuda',160)])
def test_long_text_keeps_device_length_and_all_characters_without_recombining(device,limit):
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True,device=device)
    speech.active=True;speech.ready=True;speech.process=Process()
    text=('中文和 English words，'*15)+'最后一句。'
    expected=split_for_speech(text,limit)
    speech.offer(record(0,translated=text))
    while speech.queue or speech.generating_id:
        if speech.generating_id:speech._event({'event':'speech_done','id':speech.generating_id})
        else:speech.current=None;speech._next()
        if speech.prefetched:
            speech.current=None;speech._next()
    submitted=[r['text'] for r in speech.process.commands]
    assert submitted==expected and ''.join(submitted)==text
    assert all(len(part)<=limit for part in submitted)
    speech.close();app.processEvents()
