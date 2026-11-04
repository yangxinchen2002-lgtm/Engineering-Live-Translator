import os
from dataclasses import replace
from pathlib import Path
import time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication,QFileDialog
from app.ui.window import MainWindow
from app.ui.preferences import UISettings,PreferencesStore
from app.audio.processes import ProcessInfo


@pytest.fixture
def app(monkeypatch):
    from app.ui import controller
    monkeypatch.setattr(controller,'manage_credential',lambda action:{'available':False,'source':'unavailable'})
    return QApplication.instance() or QApplication([])


def test_first_enable_prompts_once_and_remembers_folder_without_auto_capture(app,monkeypatch,tmp_path):
    chosen=[]
    def choose(*args):chosen.append(True);return str(tmp_path)
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',choose)
    window=MainWindow();window.show();app.processEvents()
    assert window.settings_tabs.currentWidget()==window.course_scroll
    window.transcript_settings_button.click();app.processEvents()
    assert window.settings_tabs.currentWidget()==window.settings_scroll
    viewport=window.settings_scroll.viewport()
    assert viewport.rect().contains(window.transcript_folder_button.mapTo(viewport,window.transcript_folder_button.rect().center()))
    assert not window.save_transcripts_check.isChecked() and window.transcript_directory is None
    window.save_transcripts_check.setChecked(True)
    assert len(chosen)==1 and window.transcript_directory==tmp_path.resolve()
    window.save_transcripts_check.setChecked(False);window.save_transcripts_check.setChecked(True)
    assert len(chosen)==1 and not window.controller.running
    window.close();app.processEvents()


def test_cancel_first_folder_selection_leaves_saving_disabled(app,monkeypatch):
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:'')
    window=MainWindow();window.show();app.processEvents();window.save_transcripts_check.setChecked(True)
    assert not window.save_transcripts_check.isChecked() and window.transcript_directory is None
    window.close();app.processEvents()


def test_saved_preference_restores_without_dialog_or_start_and_enabled_path_reaches_backend(app,monkeypatch,tmp_path):
    store=PreferencesStore(tmp_path/'ui.json')
    store.save(replace(UISettings(),save_transcripts=True,transcript_directory=str(tmp_path)))
    def forbidden(*args):raise AssertionError('remembered folder must not prompt on startup')
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',forbidden)
    window=MainWindow(preferences=store);window.show();app.processEvents()
    assert window.save_transcripts_check.isChecked() and not window.controller.running
    window.processes_ready([ProcessInfo(42,'vlc.exe','C:/vlc.exe',100)],[])
    started=[];monkeypatch.setattr(window.controller,'start',lambda *args,**kwargs:started.append(kwargs))
    window.start_capture();assert started[-1]['transcript_directory']==tmp_path
    window.running_changed(True)
    assert not window.save_transcripts_check.isEnabled() and not window.transcript_folder_button.isEnabled()
    window.running_changed(False);window.save_transcripts_check.setChecked(False);window.start_capture()
    assert started[-1]['transcript_directory'] is None
    window.close();app.processEvents()


def test_folder_and_opt_in_are_persisted_as_preferences_only(app,monkeypatch,tmp_path):
    store=PreferencesStore(tmp_path/'ui.json');window=MainWindow(preferences=store);window.show();app.processEvents()
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:str(tmp_path))
    window.save_transcripts_check.setChecked(True);window.save_preferences()
    deadline=time.monotonic()+3
    while 'preferences' in window.controller.operations and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    loaded=store.load();assert loaded.save_transcripts and loaded.transcript_directory==str(tmp_path.resolve())
    window.close();app.processEvents()


def test_save_result_and_failure_have_honest_persistent_status(app,tmp_path):
    window=MainWindow();window._save_session=True
    window.backend_event({'event':'transcript_started','path':str(tmp_path/'in-progress.txt')})
    window.backend_event({'event':'transcript_saved','transcript_path':str(tmp_path/'2026-10-31-德语-2分钟.txt'),
        'transcript_complete':True,'transcript_untranslated':0})
    window.capture_finished(0,False)
    assert '翻译稿已保存' in window.notice.text()
    window.backend_event({'event':'transcript_error','reason':'transcript_write_failed'})
    window.capture_finished(0,False)
    assert '保存出现错误' in window.notice.text() and window.transcript_failed
    window.close();app.processEvents()
