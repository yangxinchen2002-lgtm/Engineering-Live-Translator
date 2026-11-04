import os
from dataclasses import replace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from app.ui.overlay import Overlay
from app.ui.focus import completed_for_focus
from app.ui.window import MainWindow


@pytest.fixture
def app(monkeypatch):
    from app.ui import controller
    monkeypatch.setattr(controller,'manage_credential',lambda action:{'available':False,'source':'unavailable'})
    return QApplication.instance() or QApplication([])


def record(segment,**changes):
    result=dict(event='subtitle',session_id='focus-test',segment_id=segment,revision=2,candidate_revision=0,
        source_text=f'Test sentence {segment}.',translated_text=f'测试句子 {segment}。',candidate_text='',
        translated_revision=2,state='final',source_closed=True,translation_status='ready')
    result.update(changes);return result


def overlay(app,count=4):
    window=Overlay();window.resize(700,420)
    window.apply_appearance(replace(window.appearance,font_size=12,focus_mode=True,visible_segments=count))
    window.show();app.processEvents();return window


@pytest.mark.parametrize('changes',[{'state':'preview'},{'source_closed':False},{'translated_revision':1},
    {'translated_text':''},{'source_text':''}])
def test_focus_eligibility_requires_complete_matching_bilingual_record(changes):
    assert completed_for_focus(record(1),True)
    assert not completed_for_focus(record(1,**changes),True)


def test_complete_pair_is_centered_and_pending_or_late_older_results_do_not_replace_it(app):
    window=overlay(app)
    window.present_many([record(2),record(3,state='preview',source_closed=False,translated_text='')],True)
    view=window.focus;card=view.cards[2]
    assert view.current==2 and abs(card.widget.geometry().center().y()-view.rect().center().y())<=1
    window.present_many([record(1),record(2),record(3,state='preview',source_closed=False,translated_text='')],True)
    assert view.current==2 and not view.transitioning and not view.pending
    assert view.cards[2].widget is card.widget
    window.close();app.processEvents()


def test_out_cubic_animation_pushes_old_and_new_cards_together_without_fading(app):
    window=overlay(app);window.present_many([record(1)],True)
    view=window.focus;old=view.cards[1].widget;start_old=old.y()
    window.present_many([record(1),record(2)],True)
    assert view.target==2 and view.current==1
    incoming=view.cards[2].widget;start_new=incoming.y();distance=view.starts[2]-view.ends[2]
    view.animation.setCurrentTime(view.DURATION_MS//2)
    moved=start_new-incoming.y()
    assert abs(moved/distance-.875)<.03
    assert abs((start_old-old.y())-moved)<=1
    assert old.graphicsEffect() is None and incoming.graphicsEffect() is None
    view.animation.setCurrentTime(view.DURATION_MS);app.processEvents()
    assert view.current==2 and not view.transitioning
    assert view.cards[1].widget is old and old.y()<incoming.y()
    assert abs(incoming.geometry().center().y()-view.rect().center().y())<=1
    window.close();app.processEvents()


def test_new_completions_queue_without_restarting_active_push_and_burst_is_bounded(app):
    window=overlay(app);window.present_many([record(1)],True);view=window.focus
    window.present_many([record(1),record(2)],True);view.animation.setCurrentTime(120)
    for _ in range(5):window.present_many([record(1),record(2),record(3)],True)
    assert view.target==2 and len(view.pending)==1 and view.animation.currentTime()==120
    skipped=[];window.focus_coalesced.connect(skipped.append)
    window.present_many([record(index) for index in range(1,31)],True)
    assert len(view.pending)==view.QUEUE_CAPACITY and view.pending[-1]['segment_id']==30 and sum(skipped)==20
    assert len(view.cards)<=window.appearance.visible_segments+1
    # Hiding settles the newest queued card without running hidden animations.
    window.hide();app.processEvents()
    assert view.current==30 and not view.transitioning and not view.pending and not view.next_timer.isActive()
    window.close();app.processEvents()


def test_resize_and_new_session_cancel_old_animation_safely_and_source_only_is_supported(app):
    window=overlay(app);window.present_many([record(1)],True)
    window.present_many([record(1),record(2)],True);view=window.focus
    window.resize(440,300);app.processEvents()
    assert view.current==2 and not view.transitioning
    assert abs(view.cards[2].widget.geometry().center().y()-view.rect().center().y())<=1
    source=record(1,session_id='new-session',state='preview',translated_text='',translated_revision=0)
    window.present_many([source],False)
    assert view.session=='new-session' and view.current==1 and len(view.cards)==1 and not view.pending
    assert not view.cards[1].widget.translation.isVisible()
    assert completed_for_focus(source,False)
    window.clear();assert not view.cards and not view.transitioning
    window.close();app.processEvents()


def test_plain_text_markup_and_long_wrapped_pair_remain_available_after_layout_change(app):
    window=overlay(app);long=record(1,source_text='x < 0 <img src="private"> '+('long engineering sentence '*35))
    window.resize(350,180);window.present_many([long],True);app.processEvents()
    view=window.focus;row=view.cards[1].widget
    assert row.source.text()==long['source_text'] and row.height()>view.height()
    before=view.current;window.set_font(6)
    assert view.current==before and not view.transitioning and row.source.font().pointSize()==6
    window.close();app.processEvents()


def test_mode_switch_fetches_completed_record_outside_last_n_live_previews(app):
    window=MainWindow();window.show();app.processEvents()
    window.credentials_ready({'available':True});window.translate_check.setChecked(True)
    window.controller.accept_event(record(1))
    for index in range(2,10):
        window.controller.accept_event(record(index,state='preview',source_closed=False,translated_text=''))
    window.focus_check.setChecked(True);window.overlay_check.setChecked(True);window.render();app.processEvents()
    assert window.overlay.focus.current==1 and window.controller.model.current['segment_id']==9
    assert window.controller.telemetry.series['ui_delivery_focus']
    window.focus_check.setChecked(False);window.render();app.processEvents()
    assert window.overlay.record['segment_id']==9 and not window.overlay.focus.transitioning
    window.close();app.processEvents()


def test_paint_timing_uses_that_records_receipt_not_latest_incomplete_record(app,monkeypatch):
    from app.ui import controller as module
    controller=module.BackendController();times=iter((1000,9000));monkeypatch.setattr(module,'now_ns',lambda:next(times))
    first=record(1);controller.accept_event(first)
    controller.accept_event(record(2,state='preview',source_closed=False,translated_text=''))
    token=controller.begin_paint('focus',first)
    assert token==1 and controller.telemetry.pending[(token,'focus')]['received_ns']==1000
    assert controller.begin_paint('focus',record(1,revision=3)) is None
    controller.cleanup_idle()


def test_focus_preference_and_appearance_dialog_restore_without_enabling_capture(app,tmp_path):
    from app.ui.preferences import PreferencesStore,UISettings
    from app.ui.appearance import AppearanceDialog
    store=PreferencesStore(tmp_path/'ui.json');store.save(replace(UISettings(),focus_mode=True))
    window=MainWindow(preferences=store);window.show();app.processEvents()
    assert window.focus_check.isChecked() and window.overlay.appearance.focus_mode
    assert not window.controller.running and not window.overlay.isVisible()
    dialog=AppearanceDialog(window.settings_snapshot(),window)
    assert dialog.focus.isChecked();dialog.focus.setChecked(False);window.apply_settings(dialog.value())
    assert not window.focus_check.isChecked() and not window.overlay.appearance.focus_mode
    dialog.reject();window.close();app.processEvents()


def test_record_timing_map_is_bounded_and_does_not_invent_missing_old_timestamps(app):
    from app.ui.controller import BackendController
    controller=BackendController();first=record(1)
    for index in range(1,150):controller.accept_event(record(index))
    assert len(controller.paint_records)==128 and controller.begin_paint('focus',first) is None
    controller.cleanup_idle()


def test_long_caption_history_scroll_is_preserved_when_new_caption_arrives(app):
    from PySide6.QtCore import Qt,QPoint,QPointF
    from PySide6.QtGui import QWheelEvent
    window=overlay(app);window.resize(350,180)
    first=record(1,source_text='long layout test '*100);window.present_many([first],True);app.processEvents()
    view=window.focus
    event=QWheelEvent(QPointF(50,50),QPointF(100,100),QPoint(),QPoint(0,120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    QApplication.sendEvent(view,event)
    app.processEvents();assert view.browsing and view.return_button.isVisible()
    old=view.history_rows[1];before=view.history_scroll.verticalScrollBar().value()
    window.present_many([first,record(2)],True);app.processEvents()
    assert view.history_rows[1] is old and view.history_scroll.verticalScrollBar().value()==before
    assert view.browsing and view.current==2 and not view.transitioning
    window.close();app.processEvents()


def test_live_source_and_candidate_update_below_completed_focus_without_moving_it(app):
    window=overlay(app);live=record(2,state='preview',source_closed=False,translated_text='',
        source_text='The system',candidate_text='is stable')
    window.present_many([record(1),live],True);app.processEvents();view=window.focus
    completed=view.cards[1].widget;position=completed.pos();preview=view.preview
    assert view.current==1 and view.preview_record['segment_id']==2 and view.preview_clip.isVisible()
    assert 'The system' in preview.source.text() and 'is stable' in preview.source.text()
    assert not preview.translation.isVisible()
    assert view.preview_clip.y()>=completed.y()+completed.height()+view.GAP
    updated=dict(live,revision=3,source_text='The system is',candidate_text='not stable')
    window.present_many([record(1),updated],True)
    assert view.preview is preview and 'not stable' in preview.source.text()
    assert view.cards[1].widget is completed and completed.pos()==position
    assert view.current==1 and not view.transitioning and not view.pending
    window.close();app.processEvents()


def test_candidate_only_is_visible_before_first_complete_pair_and_is_html_escaped(app):
    window=overlay(app);live=record(1,state='preview',source_closed=False,source_text='',translated_text='',
        candidate_text='x < 0 <img src="private">')
    window.present_many([live],True);app.processEvents();view=window.focus
    assert not view.cards and view.preview_clip.isVisible()
    assert '&lt;' in view.preview.source.text() and '<img' not in view.preview.source.text()
    assert view.preview_record['candidate_text']==live['candidate_text']
    window.close();app.processEvents()


def test_source_waiting_translation_is_promoted_without_duplicate_preview(app):
    window=overlay(app);pending=record(2,state='preview',translated_text='',translation_status='pending')
    window.present_many([record(1),pending],True);view=window.focus
    assert view.preview_record['source_text']==pending['source_text'] and view.current==1
    window.present_many([record(1),record(2)],True)
    assert view.target==2 and view.preview_record is None and not view.preview_clip.isVisible()
    assert list(view.cards)==[1,2]
    view.animation.setCurrentTime(view.DURATION_MS);app.processEvents()
    assert view.current==2 and view.preview_record is None
    # An older unfinished sentence cannot reappear underneath a newer complete one.
    window.present_many([record(1,state='preview'),record(2)],True)
    assert view.preview_record is None
    window.close();app.processEvents()


def test_live_words_keep_up_during_push_without_restarting_animation_or_overlapping_cards(app):
    window=overlay(app);window.present_many([record(1)],True);view=window.focus
    live=record(3,state='preview',source_closed=False,translated_text='',candidate_text='next words')
    window.present_many([record(1),record(2),live],True);view.animation.setCurrentTime(220)
    before=view.cards[2].widget.pos()
    window.present_many([record(1),record(2),dict(live,candidate_revision=1,candidate_text='next words revised')],True)
    assert view.animation.currentTime()==220 and view.cards[2].widget.pos()==before
    assert view.preview_record['segment_id']==3 and 'revised' in view.preview.source.text()
    assert view.preview_clip.y()>=max(card.widget.y()+card.widget.height() for card in view.cards.values())+view.GAP
    view.animation.setCurrentTime(view.DURATION_MS);app.processEvents()
    assert view.current==2 and view.preview_clip.isVisible()
    window.close();app.processEvents()


def test_live_preview_clear_hide_and_new_session_do_not_leave_stale_text(app):
    window=overlay(app);live=record(2,state='preview',source_closed=False,translated_text='',candidate_text='current audio')
    window.present_many([record(1),live],True);window.hide();app.processEvents()
    assert window.focus.preview_record['segment_id']==2
    window.show();app.processEvents();assert window.focus.preview_clip.isVisible()
    fresh=record(1,session_id='fresh',state='preview',source_closed=False,translated_text='',source_text='new recording',candidate_text='new tail')
    window.present_many([fresh],True);window.set_font(6)
    assert window.focus.preview_record['session_id']=='fresh'
    assert 'current audio' not in window.focus.preview.source.text() and window.focus.preview.source.font().pointSize()==6
    window.clear();assert window.focus.preview_record is None and not window.focus.preview_clip.isVisible()
    window.close();app.processEvents()


def test_main_window_routes_live_text_to_focus_without_new_completed_paint_or_translation(app,monkeypatch):
    window=MainWindow();window.show();app.processEvents()
    window.credentials_ready({'available':True});window.translate_check.setChecked(True)
    window.focus_check.setChecked(True);window.overlay_check.setChecked(True)
    window.controller.accept_event(record(1));window.render();app.processEvents()
    count=len(window.controller.telemetry.series['ui_delivery_focus'])
    def forbidden(*args,**kwargs):raise AssertionError('display update must not start capture or translation')
    monkeypatch.setattr(window.controller,'start',forbidden)
    live=record(2,state='preview',source_closed=False,translated_text='',candidate_text='heard progressively')
    window.controller.accept_event(live);window.render();app.processEvents()
    assert window.overlay.focus.current==1 and 'heard progressively' in window.overlay.focus.preview.source.text()
    assert len(window.controller.telemetry.series['ui_delivery_focus'])==count
    assert not window.controller.running
    window.close();app.processEvents()
