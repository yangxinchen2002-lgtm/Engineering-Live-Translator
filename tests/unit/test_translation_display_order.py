"""A short later reply must not hide the preceding delayed translation."""
import asyncio
from dataclasses import replace
import json
import os
import time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication
from app.ui.overlay import Overlay
from tests.unit.test_ui_focus import record,overlay


@pytest.fixture
def app(monkeypatch):
    from app.ui import controller
    monkeypatch.setattr(controller,'manage_credential',lambda action:{'available':False,'source':'unavailable'})
    monkeypatch.setattr(controller.BackendController,'refresh_processes',lambda self:None)
    return QApplication.instance() or QApplication([])


def pending(index=1,**changes):
    return record(index,**{'state':'preview','translated_text':'','translation_status':'streaming',**changes})


def expire_focus_hold(view,app):
    view.read_until=0.;view.next_timer.stop();view._pump()
    if view.transitioning:view.animation.setCurrentTime(view.DURATION_MS)
    app.processEvents()


def test_later_short_reply_cannot_push_pending_long_source_out_of_single_focus(app):
    window=overlay(app,count=1);view=window.focus
    long=pending(1,source_text='Long first sentence '*30);short=record(2,source_text='Yes.',translated_text='是的。')
    window.present_many([long,short],True)
    assert view.current==1 and not view.transitioning and not view.pending
    assert view.cards[1].widget.source.text()==long['source_text']
    assert view.preview_record['segment_id']==2 and 'Yes.' in view.preview.source.text()
    ready=record(1,source_text=long['source_text'],translated_text='第一句的完整中文。'*15)
    window.present_many([ready,short],True)
    assert view.current==1 and not view.transitioning and view.next_timer.isActive()
    assert view.cards[1].widget.translation.text()==ready['translated_text']
    assert view.preview_record['segment_id']==2
    assert view.read_until-time.monotonic()>=7
    expire_focus_hold(view,app)
    assert view.current==2 and view.cards[2].widget.translation.text()=='是的。'
    window.close()


def test_live_recognition_keeps_up_while_a_later_translation_waits(app):
    window=overlay(app,count=1);view=window.focus
    live=pending(3,source_closed=False,source_text='Third source',candidate_text='still arriving')
    window.present_many([pending(),record(2),live],True)
    assert view.current==1 and 'still arriving' in view.preview.source.text()
    window.present_many([pending(),record(2),dict(live,candidate_text='newer live words')],True)
    assert view.current==1 and 'newer live words' in view.preview.source.text()
    assert not view.transitioning
    window.close()


def test_retryable_failure_holds_order_until_retry_succeeds_or_finishes(app):
    window=overlay(app);view=window.focus
    retry=pending(1,translation_status='network_timeout',translation_retry_pending=True)
    window.present_many([retry,record(2)],True)
    assert view.current==1 and not view.transitioning
    window.present_many([dict(retry,translation_retry_pending=False),record(2)],True)
    assert view.current==1 and view.next_timer.isActive()
    expire_focus_hold(view,app)
    assert view.current==2 and '原文已保留' in view.cards[1].widget.translation.text()
    window.close()


def test_recovery_batches_do_not_coalesce_away_waiting_completed_translations(app):
    window=overlay(app,count=1);view=window.focus;skipped=[]
    window.focus_coalesced.connect(skipped.append)
    records=[pending()]+[record(index) for index in range(2,22)]
    window.present_many(records,True);assert view.current==1
    records[0]=record(1);window.present_many(records,True)
    assert len(view.pending)==8 and view.highest_segment==9 and not skipped
    seen=[1]
    for _ in range(20):
        expire_focus_hold(view,app);seen.append(view.current)
    assert seen==list(range(1,22)) and not skipped
    assert len(view.cards)==1 and len(view.latest_records)<=128
    window.close()


def test_evicted_pending_focus_is_explicit_and_does_not_deadlock_display(app):
    window=overlay(app,count=1);view=window.focus;issues=[]
    view.display_issue.connect(lambda code,segment:issues.append((code,segment)))
    window.present_many([pending(),record(2)],True)
    window.present_many([record(2),record(3)],True)
    assert issues==[('translation_history_expired',1)] and view.current==1
    expire_focus_hold(view,app);assert view.current==2
    window.close()


def test_normal_list_pins_long_sentence_then_displays_short_reply_after_reading(app):
    window=Overlay();window.apply_appearance(replace(window.appearance,visible_segments=1))
    window.show();app.processEvents();first=pending();second=record(2)
    window.present_many([first,second],True)
    assert list(window.rows)==[('focus-test',1),('focus-test',2)]
    assert '前句处理中' in window.rows[('focus-test',2)].translation.text()
    ready=record(1,translated_text='先读这句完整中文。'*10)
    window.present_many([ready,second],True)
    assert window.rows[('focus-test',1)].translation.text()==ready['translated_text']
    assert window.list_hold==1 and window.list_timer.isActive()
    window.list_read_until=0.;window.list_timer.stop();window.present_many([ready,second],True)
    assert window.list_hold==2 and ('focus-test',1) not in window.rows
    assert window.rows[('focus-test',2)].translation.text()==second['translated_text']
    window.close()


def test_main_supplies_pending_older_rows_even_when_recent_count_is_one(app):
    from app.ui.window import MainWindow
    window=MainWindow();app.processEvents();window.credentials_ready({'available':True})
    window.translate_check.setChecked(True);window.sentence_spin.setValue(1)
    window.controller.accept_event(pending());window.controller.accept_event(record(2));window.render()
    assert ('focus-test',1) in window.overlay.rows
    window.close();app.processEvents()


@pytest.mark.parametrize('focus',[False,True])
def test_real_coordinator_and_concurrent_worker_preserve_visual_order_on_reverse_replies(app,focus):
    import httpx
    from tests.unit.test_translation_worker import setup
    from tests.unit.test_deepseek_client import event,chunk
    from app.translation.client import DeepSeekClient
    from app.translation.config import TranslationConfig
    from app.translation.credentials import Credential
    async def run():
        gate=asyncio.Event();short_done=asyncio.Event();window=Overlay()
        window.apply_appearance(replace(window.appearance,focus_mode=focus,visible_segments=1))
        window.show();app.processEvents();rows={};completed=[]
        async def handle(request):
            messages=json.loads(request.content)['messages']
            source=json.loads(messages[-1]['content'])['current_source_text']
            if source=='First long sentence.':await gate.wait()
            text='长句的完整译文。' if source.startswith('First') else '短句译文。'
            completed.append(source)
            if source=='Short.':short_done.set()
            body=event(chunk(text))+event(chunk(finish='stop'))+b'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=body)
        config=TranslationConfig()
        client=DeepSeekClient(config,Credential('private-test-only'),transport=httpx.MockTransport(handle))
        c,w,_=setup(client,config);original_emit=c.emit
        def emit(name,**data):
            original_emit(name,**data)
            if name=='subtitle':
                rows[data['segment_id']]=dict(data);window.present_many(list(rows.values()),True)
        c.emit=emit;c.submit_text('First long sentence.','en');c.submit_text('Short.','en')
        await asyncio.wait_for(short_done.wait(),.4)
        assert completed==['Short.'] and c.records[2].translated_text=='短句译文。'
        if focus:assert window.focus.current==1
        else:assert '前句处理中' in window.rows[(c.session_id,2)].translation.text()
        gate.set();await w.close()
        assert completed==['Short.','First long sentence.']
        if focus:
            assert window.focus.current==1 and window.focus.cards[1].widget.translation.text()=='长句的完整译文。'
            expire_focus_hold(window.focus,app);assert window.focus.current==2
        else:
            assert window.rows[(c.session_id,1)].translation.text()=='长句的完整译文。'
            window.list_read_until=0.;window.list_timer.stop();window.present_many(list(rows.values()),True)
            assert window.rows[(c.session_id,2)].translation.text()=='短句译文。'
        window.close()
    asyncio.run(run())


def test_real_qt_timer_releases_late_translation_without_another_backend_event(app):
    from PySide6.QtTest import QTest
    window=overlay(app);view=window.focus
    window.present_many([pending(),record(2)],True);window.present_many([record(1),record(2)],True)
    assert view.current==1 and view.next_timer.isActive()
    deadline=time.monotonic()+3
    while view.current!=2 and time.monotonic()<deadline:QTest.qWait(20)
    assert view.current==2
    window.close()


def test_speech_waits_for_retry_but_terminal_timeout_releases_later_speech(app):
    from app.ui.speech import SpeechController
    from app.speech.config import SpeechConfig
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True);speech.active=True
    diagnostics=[];speech.diagnostic.connect(diagnostics.append)
    retry=pending(1,translation_status='request_deadline',translation_retry_pending=True)
    speech.offer(retry);speech.offer(record(2))
    assert not speech.queue and list(speech.sources)==[1,2]
    speech.offer(dict(retry,translation_retry_pending=False))
    assert not speech.sources and speech.queue[0][0]==record(2)['translated_text']
    assert any(row['event']=='speech_skipped_untranslated' and row['segment_id']==1 for row in diagnostics)
    speech.close()
