"""User controls, lossless source fallback and matching late translations."""
import asyncio
from dataclasses import replace
import os
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF,QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from app.ui.overlay import Overlay
from app.ui.preferences import UISettings,PreferencesStore
from tests.unit.test_ui_focus import record,overlay


@pytest.fixture
def app(monkeypatch):
    from app.ui import controller
    monkeypatch.setattr(controller,'manage_credential',lambda action:{'available':False,'source':'unavailable'})
    monkeypatch.setattr(controller.BackendController,'refresh_processes',lambda self:None)
    return QApplication.instance() or QApplication([])


def test_dragged_focus_persists_and_new_sentence_pushes_to_that_position(app,tmp_path):
    window=overlay(app);view=window.focus;window.present_many([record(1)],True)
    origin=view.handle.mapToGlobal(QPoint(11,11));destination=origin+QPoint(90,-55)
    for kind,point,button,buttons in ((QEvent.MouseButtonPress,origin,Qt.LeftButton,Qt.LeftButton),
         (QEvent.MouseMove,destination,Qt.NoButton,Qt.LeftButton),(QEvent.MouseButtonRelease,destination,Qt.LeftButton,Qt.NoButton)):
        event=QMouseEvent(kind,QPointF(view.handle.mapFromGlobal(point)),QPointF(point),button,buttons,Qt.NoModifier)
        QApplication.sendEvent(view.handle,event)
    assert view.focus_x>.5 and view.focus_y<.5
    target=view.anchor();window.present_many([record(1),record(2)],True)
    view.animation.setCurrentTime(view.DURATION_MS);app.processEvents()
    center=view.cards[2].widget.geometry().center()
    assert abs(center.x()-target.x())<2 and abs(center.y()-target.y())<2
    store=PreferencesStore(tmp_path/'settings.json');store.save(window.appearance)
    restored=store.load();assert (restored.focus_x,restored.focus_y)==(view.focus_x,view.focus_y)
    window.resize(900,600);app.processEvents();center=view.cards[2].widget.geometry().center()
    assert abs(center.x()-view.anchor().x())<2 and abs(center.y()-view.anchor().y())<2
    view.set_focus_position(.5,.5,notify=True)
    window.locate.setChecked(False);assert not view.handle.isVisible()
    window.close()


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-.01,1.01,True,'0.5'])
def test_invalid_focus_preference_is_rejected(value):
    with pytest.raises(ValueError):replace(UISettings(),focus_x=value).validate()


@pytest.mark.parametrize('status',['network_timeout','request_deadline','rate_limited','unavailable','translation_expired'])
def test_failed_translation_keeps_original_and_late_translation_fills_same_card(app,status):
    window=overlay(app);failed=record(1,state='preview',translated_text='',translation_status=status)
    window.present_many([failed],True);view=window.focus;card=view.cards[1]
    assert view.current==1 and card.widget.source.text()==failed['source_text']
    assert '原文已保留' in card.widget.translation.text() and failed['state']=='preview'
    retry=dict(failed,translation_status='streaming',translated_text='未完成的流')
    window.present_many([retry],True)
    assert view.cards[1] is card and view.preview_record is None
    assert '未完成的流' not in card.widget.translation.text()
    window.present_many([record(1)],True)
    assert view.cards[1] is card and card.widget.translation.text()==record(1)['translated_text']
    assert view.current==1 and not view.transitioning
    window.close()


def test_network_delays_do_not_discard_closed_source_when_next_sentence_arrives(app):
    window=overlay(app);waiting=record(1,state='preview',translated_text='',translation_status='streaming')
    live=record(2,state='preview',source_closed=False,translated_text='',candidate_text='more audio')
    window.present_many([waiting,live],True);view=window.focus
    assert view.current==1 and view.cards[1].widget.source.text()==waiting['source_text']
    assert view.preview_record['segment_id']==2
    window.present_many([waiting,record(2)],True);view.animation.setCurrentTime(view.DURATION_MS)
    assert view.current==1  # a later reply waits for the earlier sentence
    window.present_many([record(1),record(2)],True)
    assert view.current==1 and view.next_timer.isActive()
    view.read_until=0.;view.next_timer.stop();view._pump();view.animation.setCurrentTime(view.DURATION_MS)
    assert view.current==2 and not view.transitioning and view.cards[1].widget.translation.text()==record(1)['translated_text']
    window.close()


def test_tall_completed_text_never_uses_live_source_reserved_band(app):
    window=overlay(app);window.resize(350,210)
    window.present_many([record(1,source_text='long sentence '*160),record(2,state='preview',source_closed=False,
                        translated_text='',candidate_text='new words remain visible')],True)
    app.processEvents();view=window.focus
    assert view.preview_clip.isVisible() and view.preview_clip.height()>=24
    assert 'remain visible' in view.preview.source.text()
    assert view.card_clip.geometry().bottom()<view.preview_clip.y()
    window.close()


def test_overlay_speed_is_bidirectional_and_does_not_start_speech(app):
    from app.ui.window import MainWindow
    window=MainWindow();app.processEvents();assert not window.speech.active
    window.overlay.base_speed.setValue(1.65)
    assert window.speech_speed.value()==1.65 and window.speech.config.speed==1.65
    window.speech_speed.setValue(.8)
    assert window.overlay.base_speed.value()==.8 and window.settings_snapshot().speech_speed==.8
    assert not window.speech.active and not window.controller.running
    window.close()


def test_pause_control_requires_native_ack_and_serializes_commands(app):
    from app.ui.controller import BackendController
    controller=BackendController();real=controller.process;sent=[]
    controller.process=SimpleNamespace(write=lambda command:sent.append(command) or len(command))
    controller.toggle_pause();assert not sent
    controller.running=True;controller.accept_event({'event':'audio_source_ready'})
    controller.toggle_pause();assert controller.pause_pending and not controller.paused and sent==[b'PAUSE\n']
    controller.toggle_pause();assert len(sent)==1
    controller.accept_event({'event':'audio_capture_paused','sample':320})
    assert controller.paused and not controller.pause_pending and not controller.pause_timer.isActive()
    controller.toggle_pause();assert sent[-1]==b'RESUME\n' and controller.paused
    controller.accept_event({'event':'audio_capture_resumed','sample':320})
    assert not controller.paused and not controller.pause_pending
    controller.running=False;controller.process=real;controller.cleanup_idle()


def test_pause_deadline_stops_instead_of_claiming_success(app,monkeypatch):
    from app.ui.controller import BackendController
    controller=BackendController();stopped=[];problems=[]
    monkeypatch.setattr(controller,'stop',lambda:stopped.append(True));controller.problem.connect(problems.append)
    controller._pause_timeout();assert stopped==[True] and problems
    controller.cleanup_idle()


def test_main_pause_button_suspends_speech_until_resume_ack(app,monkeypatch):
    from app.ui.window import MainWindow
    window=MainWindow();app.processEvents();controller=window.controller
    original=controller.process;sent=[]
    controller.process=SimpleNamespace(write=lambda command:sent.append(command) or len(command))
    controller.running=True;controller.accept_event({'event':'audio_source_ready'})
    assert window.pause_button.isEnabled()
    window.pause_button.click();assert window.speech.user_paused and not window.pause_button.isEnabled()
    controller.accept_event({'event':'audio_capture_paused','sample':320})
    assert window.pause_button.text()=='继续' and window.pause_button.isEnabled()
    window.pause_button.click();assert window.speech.user_paused
    controller.accept_event({'event':'audio_capture_resumed','sample':320})
    assert not window.speech.user_paused and window.pause_button.text()=='暂停'
    assert sent==[b'PAUSE\n',b'RESUME\n']
    controller.running=False;controller.process=original;window.close();app.processEvents()


def test_speech_pause_keeps_buffers_and_does_not_restart_failed_speech(app,monkeypatch):
    from app.ui.speech import SpeechController
    speech=SpeechController();speech.timer.stop();calls=[]
    sink=SimpleNamespace(suspend=lambda:calls.append('suspend'),resume=lambda:calls.append('resume'))
    speech.sink=sink;speech.queue.append(('保持这个句子。',1));speech.current={'playing':True}
    speech.pause_playback(True);speech._play_tick()
    assert speech.user_paused and list(speech.queue)==[('保持这个句子。',1)] and calls==['suspend']
    speech.pause_playback(False);assert calls[-1]=='resume' and speech.catch_up_started
    speech.paused=True;speech.pause_playback(True);speech.pause_playback(False)
    assert calls==['suspend','resume','suspend'] and speech.paused
    speech.sink=None;speech.current=None;speech.close()


def test_transcript_documents_intentionally_excluded_pause(tmp_path):
    from app.subtitles.transcript import TranscriptWriter
    async def run():
        now=[0];writer=TranscriptWriter(tmp_path,'focus-test','de',lambda *a,**k:None,clock=lambda:now[0])
        writer.start();writer.source_started();writer.offer({**record(1),'source_language':'de','start_sample':0})
        now[0]=10_000_000_000;writer.capture_pause(True);writer.capture_pause(True)
        now[0]=75_000_000_000;writer.capture_pause(False)
        result=await writer.close(source_complete=True)
        from pathlib import Path
        text=Path(result['transcript_path']).read_text(encoding='utf-8')
        assert '手动暂停：1次，约65秒' in text and result['transcript_minutes']==1
    asyncio.run(run())


def test_retry_exposes_original_before_retry_finishes(app):
    from tests.unit.test_translation_worker import setup,Client
    from app.translation.client import ProviderError,StreamEvent
    from app.translation.config import TranslationConfig
    async def run():
        gate=asyncio.Event();retry=asyncio.Event();window=overlay(app)
        class Flaky(Client):
            async def stream(self,messages):
                self.calls+=1
                if self.calls==1:raise ProviderError('network_timeout',retryable=True)
                retry.set();await gate.wait();yield StreamEvent('delta',text='后来补上的中文。');yield StreamEvent('done')
        coordinator,worker,_=setup(Flaky(),replace(TranslationConfig(),retry_delay_seconds=.001,finish_grace_seconds=1))
        # Route real coordinator records through the real overlay widget.
        original_emit=coordinator.emit
        def emit(name,**data):
            original_emit(name,**data)
            if name=='subtitle':window.present_many([data],True)
        coordinator.emit=emit;coordinator.submit_text('Original remains visible.','en')
        await asyncio.wait_for(retry.wait(),.3)
        view=window.focus;assert view.current==1 and 'Original remains visible.'==view.cards[1].widget.source.text()
        card=view.cards[1];assert card.record['state']=='preview'
        gate.set();await worker.close()
        assert view.cards[1] is card and card.widget.translation.text()=='后来补上的中文。'
        window.close()
    asyncio.run(run())
