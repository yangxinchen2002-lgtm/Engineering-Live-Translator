"""Manual history is detached from live focus, without pausing the pipeline."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from tests.unit.test_ui_focus import record,overlay


@pytest.fixture
def app(monkeypatch):
    from app.ui import controller
    monkeypatch.setattr(controller,'manage_credential',lambda action:{'available':False,'source':'unavailable'})
    monkeypatch.setattr(controller.BackendController,'refresh_processes',lambda self:None)
    return QApplication.instance() or QApplication([])


def wheel(target,amount=120,*,pixels=0):
    event=QWheelEvent(QPointF(40,40),QPointF(100,100),QPoint(0,pixels),QPoint(0,amount),
                      Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    QApplication.sendEvent(target,event)


def process(app):
    for _ in range(3):app.processEvents()


def test_scroll_can_reach_older_rows_even_when_recent_count_is_one(app):
    window=overlay(app,count=1);view=window.focus;rows=[record(i) for i in range(1,31)]
    window.present_many(rows,True);assert list(view.cards)==[30] and not view.return_button.isVisible()
    wheel(view);process(app)
    assert view.browsing and view.history_scroll.isVisible() and view.return_button.isVisible()
    assert len(view.history_rows)==30 and 'Test sentence 1.' in view.history_rows[1].source.text()
    assert view.history_rows[1].translation.text()==record(1)['translated_text']
    assert not view.card_clip.isVisible() and not view.preview_clip.isVisible() and not view.handle.isVisible()
    view.history_scroll.verticalScrollBar().setValue(0)
    assert view.history_rows[1].geometry().intersects(view.history_scroll.viewport().rect())
    assert view.return_button.geometry().bottom()<view.height() and view.return_button.x()>0
    window.close();process(app)


def test_incoming_captions_do_not_move_history_and_return_uses_custom_focus(app):
    window=overlay(app,count=2);view=window.focus
    view.set_focus_position(.65,.35,notify=True)
    rows=[record(i) for i in range(1,21)];window.present_many(rows,True)
    wheel(view);process(app);bar=view.history_scroll.verticalScrollBar();bar.setValue(120)
    anchor=bar.value();old=view.history_rows[3];settled=[];window.focus_settled.connect(settled.append)
    for i in range(21,27):window.present_many(rows+[record(j) for j in range(21,i+1)],True)
    process(app)
    assert view.browsing and bar.value()==anchor and view.history_rows[3] is old
    assert list(view.history_rows)==list(range(1,21)) and not settled
    assert view.current==26 and not view.transitioning and not view.pending
    view.return_button.click();process(app)
    assert not view.browsing and not view.return_button.isVisible() and not view.history_scroll.isVisible()
    assert view.current==26 and view.card_clip.isVisible() and view.handle.isVisible()
    center=view.cards[26].widget.geometry().center()
    assert abs(center.x()-view.anchor().x())<2 and abs(center.y()-view.anchor().y())<2
    assert window.appearance.focus_x==.65 and window.appearance.focus_y==.35
    window.close();process(app)


def test_late_translation_reflow_preserves_visible_sentence_and_offset(app):
    window=overlay(app,count=1);view=window.focus
    waiting=record(2,state='preview',translated_text='',translation_status='request_deadline')
    rows=[record(1),waiting]+[record(i) for i in range(3,20)]
    window.present_many(rows,True);wheel(view);process(app)
    bar=view.history_scroll.verticalScrollBar();bar.setValue(view.history_rows[10].y()+7)
    before=bar.value()-view.history_rows[10].y()
    rows[1]=record(2,translated_text='迟到的中文内容。'*60)
    window.present_many(rows,True);process(app)
    assert view.browsing and view.history_rows[2].translation.text()==rows[1]['translated_text']
    assert abs((bar.value()-view.history_rows[10].y())-before)<=1
    window.close();process(app)


def test_history_is_a_bounded_snapshot_and_does_not_grow_during_long_browse(app):
    window=overlay(app,count=1);view=window.focus
    rows=[record(i) for i in range(1,161)];window.present_many(rows,True);wheel(view);process(app)
    assert len(view.history_snapshot)==128 and min(view.history_snapshot)==33
    bar=view.history_scroll.verticalScrollBar();bar.setValue(0);first=view.history_rows[33]
    window.present_many([record(i) for i in range(161,301)],True);process(app)
    assert len(view.history_rows)==128 and view.history_rows[33] is first and bar.value()==0
    assert len(view.latest_records)==128 and view.current==300
    view.return_button.click();process(app);wheel(view);process(app)
    assert min(view.history_snapshot)==173 and max(view.history_snapshot)==300
    window.close();process(app)


def test_browse_during_animation_and_resume_does_not_replay_hidden_pushes(app):
    window=overlay(app);view=window.focus;window.present_many([record(1)],True)
    window.present_many([record(1),record(2),record(3)],True);view.animation.setCurrentTime(200)
    wheel(view);process(app)
    assert view.browsing and not view.transitioning and not view.next_timer.isActive()
    view.return_button.click();process(app)
    assert view.current==3 and not view.transitioning and not view.pending
    window.close();process(app)


def test_return_still_waits_for_earlier_unfinished_translation(app):
    window=overlay(app);view=window.focus
    waiting=record(1,state='preview',translated_text='',translation_status='streaming')
    window.present_many([waiting,record(2)],True);wheel(view);process(app)
    window.present_many([waiting,record(2),record(3)],True)
    view.return_button.click();process(app)
    assert view.current==1 and not view.transitioning and view.preview_record['segment_id']==3
    window.close();process(app)


def test_resize_font_and_mouse_passthrough_do_not_leave_history_or_move_focus(app):
    window=overlay(app);view=window.focus;window.present_many([record(i) for i in range(1,21)],True)
    wheel(view);process(app);window.set_font(10);window.resize(520,360);process(app)
    assert view.browsing and view.history_rows[1].source.font().pointSize()==10
    window.set_click_through(True);assert not view.handle.isVisible()
    window.set_click_through(False);process(app);assert not view.handle.isVisible() and view.return_button.isVisible()
    view.return_button.click();process(app);assert view.handle.isVisible()
    window.close();process(app)


@pytest.mark.parametrize('action',['clear','new_session','mode_switch'])
def test_history_reset_never_leaves_previous_session_text_or_return_button(app,action):
    window=overlay(app);view=window.focus;window.present_many([record(1),record(2)],True)
    wheel(view);process(app);assert view.browsing
    if action=='clear':window.clear()
    elif action=='new_session':window.present_many([record(1,session_id='fresh')],True)
    else:window.apply_appearance(replace(window.appearance,focus_mode=False))
    process(app)
    assert not view.browsing and not view.history_rows and not view.history_snapshot
    assert not view.return_button.isVisible() and not view.history_layout_timer.isActive()
    window.close();process(app)


def test_no_content_or_zero_wheel_does_not_show_return_button(app):
    window=overlay(app);view=window.focus;wheel(view);process(app)
    assert not view.browsing and not view.return_button.isVisible()
    window.present_many([record(1)],True);wheel(view,0);process(app)
    assert not view.browsing
    wheel(view,0,pixels=25);process(app);assert view.browsing
    window.close();process(app)


def test_history_viewport_wheel_and_reflow_wheel_do_not_undo_user_scroll(app):
    window=overlay(app,count=1);view=window.focus
    rows=[record(i) for i in range(1,26)];window.present_many(rows,True);wheel(view);process(app)
    bar=view.history_scroll.verticalScrollBar();before=bar.value()
    wheel(view.history_scroll.viewport());process(app);assert bar.value()<before
    bar.setValue(view.history_rows[15].y()+8);offset=bar.value()-view.history_rows[15].y()
    rows[1]=record(2,translated_text='较长的迟到译文。'*40);window.present_many(rows,True)
    assert view.history_anchor is not None
    wheel(view.history_scroll.viewport());process(app)
    assert abs((bar.value()-view.history_rows[15].y())-(offset-40))<=1
    window.close();process(app)


def test_fast_return_cancels_pending_layout_and_new_session_is_clean(app):
    window=overlay(app);view=window.focus;window.present_many([record(1),record(2)],True)
    wheel(view);assert view.history_layout_timer.isActive()
    view.return_button.click();process(app)
    assert not view.browsing and not view.history_layout_timer.isActive() and view.current==2
    wheel(view);window.present_many([record(1,session_id='fresh')],True);process(app)
    assert not view.browsing and view.session=='fresh' and not view.return_button.isVisible()
    window.close();process(app)


def test_history_controls_do_not_pause_capture_translation_or_reading(app,monkeypatch):
    from app.ui.window import MainWindow
    window=MainWindow();process(app);window.focus_check.setChecked(True);window.overlay_check.setChecked(True)
    for i in range(1,8):window.controller.accept_event(record(i))
    window.render();process(app);window.controller.running=True
    def forbidden(*args,**kwargs):raise AssertionError('history must only change rendering')
    for name in ('start','stop','toggle_pause'):monkeypatch.setattr(window.controller,name,forbidden)
    monkeypatch.setattr(window.speech,'pause_playback',forbidden)
    wheel(window.overlay.focus);process(app)
    window.controller.accept_event(record(8));window.render();process(app)
    window.overlay.focus.return_button.click();process(app)
    assert window.controller.running and not window.controller.paused and window.overlay.focus.current==8
    assert any(event['event']=='subtitle_history_browsing' and event['active'] for event in window.controller.diagnostics)
    window.controller.running=False;window.close();process(app)


def test_source_only_history_hides_waiting_chinese_when_mode_changes(app):
    window=overlay(app);view=window.focus
    first=record(1,state='preview',translated_text='',translation_status='request_deadline')
    window.present_many([first],True);wheel(view);process(app)
    assert view.history_rows[1].translation.isVisible()
    window.present_many([first],False);process(app)
    assert view.browsing and not view.history_rows[1].translation.isVisible()
    window.close();process(app)


def test_return_button_fits_small_overlay(app):
    window=overlay(app);window.resize(280,120);window.present_many([record(1),record(2)],True)
    wheel(window.focus);process(app)
    assert window.focus.rect().contains(window.focus.return_button.geometry())
    window.close();process(app)
