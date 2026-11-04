import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import pytest
from PySide6.QtWidgets import QApplication,QFileDialog
from app.ui.window import MainWindow
from app.ui.preferences import UISettings,PreferencesStore
from tests.unit.test_speech_and_course_notes import record


@pytest.fixture
def app(monkeypatch):
    from app.ui import controller
    monkeypatch.setattr(controller,'manage_credential',lambda action:{'available':False,'source':'unavailable'})
    return QApplication.instance() or QApplication([])


def test_voice_device_and_summary_preferences_restore_without_loading_a_model(app,tmp_path):
    store=PreferencesStore(tmp_path/'prefs.json')
    settings=replace(UISettings(),speech_enabled=True,speech_device='cpu',speech_voice='uncle_fu',
                     speech_volume=45,speech_speed=1.6,speech_auto_catch_up=False,speech_duck_source=False,
                     speech_catch_up_start_chars=120,speech_catch_up_grace_seconds=7,
                     speech_source_percent=35,auto_summary=True,transcript_directory=str(tmp_path))
    store.save(settings);window=MainWindow(preferences=store);app.processEvents()
    assert window.speech_device.currentData()=='cpu' and window.speech_voice.currentData()=='uncle_fu'
    assert window.speech_check.isChecked() and window.auto_summary_check.isChecked()
    assert window.speech.process is None and not window.controller.running
    assert window.settings_snapshot().speech_volume==45
    assert window.speech_speed.value()==1.6 and not window.speech_catch_up.isChecked()
    assert window.speech_catch_chars.value()==120 and window.speech_catch_grace.value()==7
    assert window.speech.config.catch_up_start_chars==120 and window.speech.config.catch_up_grace_seconds==7
    assert window.source_duck_percent.value()==35 and not window.source_duck_check.isChecked()
    assert window.settings_snapshot().speech_source_percent==35
    window.speech_speed.setValue(1.4);app.processEvents()
    assert window.speech.config.speed==1.4 and window.speech.process is None
    window.close();app.processEvents()


def test_manual_ai_notes_use_full_session_even_when_txt_saving_is_off(app,tmp_path,monkeypatch):
    window=MainWindow();app.processEvents();window.credential_status={'available':True}
    window.transcript_directory=tmp_path
    for index in range(300):window.controller.accept_event(record(index,text=f'原文{index}',translated=f'中文{index}'))
    assert len(window.controller.model.records)==128
    calls=[];monkeypatch.setattr(window.notes,'generate',lambda payload,directory:calls.append((payload,directory)))
    assert not window.save_transcripts_check.isChecked()
    assert window.generate_current_notes() and len(calls[0][0]['records'])==300
    window.close();app.processEvents()


def test_auto_summary_is_once_per_finished_session_and_folder_cancel_is_respected(app,tmp_path,monkeypatch):
    window=MainWindow();app.processEvents();window.credential_status={'available':True}
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:'')
    window.auto_summary_check.setChecked(True)
    assert not window.auto_summary_check.isChecked()
    window.transcript_directory=tmp_path;window.auto_summary_check.setChecked(True)
    window.running_changed(True);window.controller.accept_event(record(0))
    window.running_changed(False);calls=[]
    monkeypatch.setattr(window.notes,'generate',lambda *args:calls.append(args))
    window.capture_finished(0,False);window.capture_finished(0,False)
    assert len(calls)==1
    window.close();app.processEvents()


def test_running_session_keeps_voice_and_device_switches_available(app,monkeypatch):
    window=MainWindow();app.processEvents();window.running_changed(True)
    assert window.speech_voice.isEnabled() and window.speech_device.isEnabled()
    assert window.speech_model.isEnabled()
    assert window.speech_speed.isEnabled() and window.speech_catch_up.isEnabled()
    assert not window.speech_preview_button.isEnabled() and not window.auto_summary_check.isEnabled()
    window.running_changed(False);window.close();app.processEvents()


def test_source_volume_follows_speech_and_manual_override_without_model_load(app,monkeypatch):
    from app.audio.processes import ProcessInfo
    from app.speech.config import SpeechConfig
    window=MainWindow();app.processEvents();calls=[]
    monkeypatch.setattr(window.source_volume,'set_target',lambda target,percent:calls.append((target,percent)))
    target=ProcessInfo(100,'vlc.exe','C:/VLC/vlc.exe',200)
    window.controller.capture_target=target;window.controller.running=True
    window.translate_check.setChecked(True);window.speech.config=SpeechConfig(True);window.speech.active=True
    window.sync_source_volume();assert calls[-1]==(target,20)
    window.source_duck_percent.setValue(35);assert calls[-1]==(target,35)
    window.source_duck_check.setChecked(False);assert calls[-1]==(None,35)
    window.source_duck_check.setChecked(True);assert calls[-1]==(target,35)
    window.speech.paused=True;window.sync_source_volume();assert calls[-1]==(None,35)
    window.speech.paused=False;window.controller.running=False;window.speech.active=False
    window.speech.finishing=True;window.speech.current={'id':'test'}
    window.sync_source_volume();assert calls[-1]==(target,35)
    window.speech.stop();assert calls[-1]==(None,35)
    assert window.source_duck_percent.minimum()==10 and window.source_duck_percent.maximum()==100
    window.close();app.processEvents()
