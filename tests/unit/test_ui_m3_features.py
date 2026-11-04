import os
import time
from dataclasses import replace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from app.ui.window import MainWindow
from app.ui.appearance import AppearanceDialog
from app.ui.preferences import PreferencesStore


@pytest.fixture
def app(monkeypatch):
    from app.ui import controller
    monkeypatch.setattr(controller,'manage_credential',lambda action:{'available':False,'source':'unavailable'})
    return QApplication.instance() or QApplication([])


def record(segment,revision=1,**changes):
    return dict(event='subtitle',session_id='ui-test',segment_id=segment,revision=revision,candidate_revision=0,
        source_text=f'Sentence {segment}.',candidate_text='',translated_text=f'句子 {segment}。',
        translated_revision=revision,state='preview',**changes)


def test_overlay_shows_multiple_matching_pairs_reuses_rows_and_retains_order(app):
    window=MainWindow();window.show();app.processEvents()
    for index in range(1,9):window.controller.model.update(record(index))
    window.overlay_check.setChecked(True);window.render();app.processEvents()
    assert list(window.overlay.rows)==[('ui-test',index) for index in (5,6,7,8)]
    old=window.overlay.rows[('ui-test',5)]
    window.controller.model.update(record(5,2));window.render()
    assert window.overlay.rows[('ui-test',5)] is old
    assert window.overlay.record['segment_id']==8 and old.translation.text()=='句子 5。'
    window.sentence_spin.setValue(2)
    assert list(window.overlay.rows)==[('ui-test',7),('ui-test',8)]
    window.sentence_spin.setValue(8)
    assert len(window.overlay.rows)==8
    window.close();app.processEvents()


def test_tiny_font_and_numeric_dimensions_update_all_visible_rows(app):
    window=MainWindow();window.show();app.processEvents()
    for index in range(1,5):window.controller.model.update(record(index))
    window.render();window.font_value.setValue(6)
    assert window.font_slider.minimum()==6 and window.font_slider.maximum()==72
    assert window.source.font().pointSize()==6
    assert all(row.source.font().pointSize()==6 and row.translation.font().pointSize()==6 for row in window.overlay.rows.values())
    dialog=AppearanceDialog(window.settings_snapshot(),window)
    dialog.width_value.setValue(380);dialog.height_value.setValue(180);dialog.lines.setValue(3)
    window.apply_settings(dialog.value())
    assert window.overlay.width()==380 and window.overlay.height()==180 and len(window.overlay.rows)==3
    dialog.reject();window.close();app.processEvents()


def test_click_through_has_visible_recovery_and_hide_resets_it(app):
    window=MainWindow();window.show();app.processEvents()
    window.mouse_check.setChecked(True);app.processEvents()
    assert window.overlay.click_through and window.overlay.isVisible() and window.overlay_check.isChecked()
    window.recover_overlay()
    assert not window.overlay.click_through and window.overlay.isVisible()
    window.mouse_check.setChecked(True);window.overlay.hide();app.processEvents()
    assert not window.overlay.click_through and not window.mouse_check.isChecked() and not window.overlay_check.isChecked()
    window.close();app.processEvents()


def test_preferences_save_without_credentials_and_restore_appearance_not_capture(app,tmp_path):
    store=PreferencesStore(tmp_path/'ui.json')
    window=MainWindow(preferences=store);window.show();app.processEvents()
    window.font_value.setValue(8);window.sentence_spin.setValue(6);window.overlay.resize(720,280)
    window.save_preferences()
    deadline=time.monotonic()+3
    while 'preferences' in window.controller.operations and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    assert store.load().font_size==8 and store.load().visible_segments==6
    window.close();app.processEvents()
    reopened=MainWindow(preferences=store);reopened.show();app.processEvents()
    assert reopened.font_value.value()==8 and reopened.sentence_spin.value()==6
    assert reopened.overlay.width()==720 and reopened.overlay.height()==280
    assert not reopened.controller.running and not reopened.translate_check.isChecked()
    assert not reopened.overlay.isVisible() and not reopened.overlay.click_through
    reopened.close();app.processEvents()


def test_caption_paint_timestamps_keep_64_bits_and_no_records_are_fabricated(app):
    from app.ui.overlay import CaptionLabel
    from PySide6.QtTest import QSignalSpy
    label=CaptionLabel('test only');spy=QSignalSpy(label.painted);label.show()
    label.set_caption('actual widget paint',12);app.processEvents()
    assert spy.count()==1 and spy.at(0)[0]==12 and spy.at(0)[1]>2**31
    label.close()


def test_header_drag_moves_window_and_release_or_input_mode_clears_drag(app):
    from PySide6.QtCore import Qt,QPointF,QEvent
    from PySide6.QtGui import QMouseEvent
    from app.ui.overlay import Overlay
    overlay=Overlay();overlay.move(100,100);overlay.show();app.processEvents()
    def mouse(kind,local,global_pos,button,buttons):
        QApplication.sendEvent(overlay,QMouseEvent(kind,QPointF(*local),QPointF(*global_pos),button,buttons,Qt.NoModifier))
    mouse(QEvent.MouseButtonPress,(100,20),(200,120),Qt.LeftButton,Qt.LeftButton)
    mouse(QEvent.MouseMove,(150,50),(250,150),Qt.NoButton,Qt.LeftButton)
    assert (overlay.x(),overlay.y())==(150,130)
    mouse(QEvent.MouseButtonRelease,(100,20),(250,150),Qt.LeftButton,Qt.NoButton)
    assert overlay._drag_offset is None
    mouse(QEvent.MouseButtonPress,(100,20),(250,150),Qt.LeftButton,Qt.LeftButton)
    overlay.set_click_through(True)
    assert overlay._drag_offset is None
    overlay.close();app.processEvents()


def test_translation_mode_is_sent_to_start_and_frozen_during_capture(app,monkeypatch):
    from app.audio.processes import ProcessInfo
    window=MainWindow();window.show();app.processEvents()
    assert window.translation_mode.currentData()=='sentence'
    window.processes_ready([ProcessInfo(42,'vlc.exe','C:/vlc.exe',100)],[])
    window.credentials_ready({'available':True});window.translate_check.setChecked(True)
    started=[];monkeypatch.setattr(window.controller,'start',lambda *args,**kwargs:started.append((args,kwargs)))
    for mode in ('sentence','preview'):
        window.translation_mode.setCurrentIndex(window.translation_mode.findData(mode));window.start_capture()
        assert started[-1][1]['translation_mode']==mode and started[-1][0][2] is True
    window.running_changed(True);assert not window.translation_mode.isEnabled()
    window.running_changed(False);assert window.translation_mode.isEnabled()
    window.close();app.processEvents()


def test_waiting_sentence_status_is_readable_in_both_views_and_mode_persists(app,tmp_path):
    store=PreferencesStore(tmp_path/'ui.json');store.save(replace(store.load(),translation_mode='preview'))
    window=MainWindow(preferences=store);window.show();app.processEvents()
    assert window.translation_mode.currentData()=='preview'
    window.translation_mode.setCurrentIndex(window.translation_mode.findData('sentence'))
    window.credentials_ready({'available':True});window.translate_check.setChecked(True);window.overlay_check.setChecked(True)
    item=record(1);item.update(translated_text='',translated_revision=0,translation_status='waiting_sentence',source_closed=False)
    window.controller.model.update(item);window.render()
    assert '等待整句' in window.translation.text() and '等待整句' in window.overlay.translation.text()
    assert window.controller.model.current['source_text'] in window.source.text()
    window.save_preferences()
    deadline=time.monotonic()+3
    while 'preferences' in window.controller.operations and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    assert store.load().translation_mode=='sentence' and not window.controller.running
    window.close();app.processEvents()
