import base64
from dataclasses import replace
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication
from app.speech.config import SpeechConfig
from app.ui.speech import SpeechController
from tests.unit.test_speech_and_course_notes import record


class Process:
    def __init__(self):self.commands=[]
    def write(self,data):self.commands.append(json.loads(data));return len(data)
    def state(self):return QProcess.NotRunning
    def deleteLater(self):pass


def test_next_utterance_is_prepared_before_current_playback_ends_in_order():
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.config=SpeechConfig(True);speech.active=True;speech.ready=True
    process=Process();speech.process=process
    texts=[f'第{index}段译文。'+('这一段需要完整保留，朗读的顺序也必须保持一致。'*4) for index in range(3)]
    for index,text in enumerate(texts):speech.offer(record(index,translated=text))
    assert [c['text'] for c in process.commands]==texts[:1]
    audio=base64.b64encode(b'\x01\x00'*24000).decode()
    speech._event({'event':'speech_audio','id':'1','rate':24000,'pcm':audio})
    speech._event({'event':'speech_done','id':'1'})
    assert speech.current['id']=='1' and not speech.current['playing']
    assert speech.prefetched[0]['id']=='2' and speech.generating_id=='2'
    assert [c['text'] for c in process.commands]==texts[:2]
    speech._event({'event':'speech_audio','id':'2','rate':24000,'pcm':audio})
    speech._event({'event':'speech_done','id':'2'})
    assert [c['text'] for c in process.commands]==texts
    speech.current=None;speech._next()
    assert speech.current['id']=='2' and speech.current['samples']==24000
    assert speech.current['raw'][0]==b'\x01\x00'*24000
    assert speech.prefetched[0]['id']=='3' and len(process.commands)==3
    speech.stop()
    assert speech.current is None and not speech.prefetched and speech.generating_id is None and not speech.queue
    speech.close();app.processEvents()


def test_pending_age_alone_never_accelerates_and_manual_speed_is_respected(monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr('app.ui.speech.now_ns',lambda:60_000_000_000)
    speech=SpeechController();speech.config=SpeechConfig(True,speed=1.25)
    assert speech._desired_speed()==1.25
    speech.queue.append(('需要完整保留的译文。',20_000_000_000))
    speech.catch_up_started=True
    assert speech._desired_speed()==1.25
    speech.config=replace(speech.config,auto_catch_up=False,speed=1.1)
    assert speech._desired_speed()==1.1
    speech.config=replace(speech.config,auto_catch_up=True,speed=2.)
    assert speech._desired_speed()==2.
    speech.close();app.processEvents()


def test_finished_preview_model_is_reused_when_starting_a_course():
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.config=SpeechConfig(True);speech.ready=True
    process=Process();speech.process=process
    speech.start('course')
    assert speech.process is process and speech.ready and speech.active and speech.session=='course'
    assert not process.commands
    speech.close();app.processEvents()


def test_current_sentence_wait_age_is_not_counted_as_new_backlog(monkeypatch):
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr('app.ui.speech.now_ns',lambda:60_000_000_000)
    speech=SpeechController();speech.config=SpeechConfig(True);speech.active=True
    speech.current={'queued_ns':0,'playback_started_ns':40_000_000_000}
    speech.catch_up_started=True
    assert speech._desired_speed()==1.25
    speech.current={'queued_ns':39_000_000_000,'playback_started_ns':40_000_000_000}
    assert speech._desired_speed()==1.25
    speech.close();app.processEvents()
