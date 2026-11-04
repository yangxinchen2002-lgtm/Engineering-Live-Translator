import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
from types import SimpleNamespace
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from app.ui.window import MainWindow
from app.ui import controller as module


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


def test_web_mode_is_available_without_a_process_and_does_not_start_tts(app):
    w=MainWindow()
    try:
        w.capture_mode.setCurrentIndex(w.capture_mode.findData('web'))
        assert w.start_button.isEnabled() and '视频预读' in w.start_button.text()
        assert w.process_combo.isHidden() and w.speech_model.isEnabled()
        assert w.web_player_choice.currentData()=='internal' and w.web_speech_engine.currentData()=='qwen'
        w.web_speech_engine.setCurrentIndex(w.web_speech_engine.findData('system'))
        assert w.speech_model.isEnabled() and w.speech_model.currentData()=='system' and not w.speech_device.isEnabled()
        assert not w.speech.active and not w.controller.running
        w.pause_changed();assert not w.pause_button.isEnabled()
        w.overlay_check.setChecked(True);assert not w.overlay.isVisible()
        w.capture_mode.setCurrentIndex(w.capture_mode.findData('audio'))
        assert w.start_button.text()=='开始字幕' and w.speech_model.isEnabled()
    finally:w.close();app.processEvents()


def test_web_backend_configuration_uses_stdin_and_ready_nonce_is_not_logged(app,monkeypatch,tmp_path):
    model=tmp_path/'model';model.mkdir();(model/'model.bin').touch()
    monkeypatch.setattr(module.ASRConfig,'load',lambda *a,**k:SimpleNamespace(model=str(model)))
    class Job:
        name='Local\\ELT.Gui.test-only'
        def close(self):pass
    monkeypatch.setattr(module,'OwnerJob',Job)
    controller=module.BackendController();controller.process.start=lambda:None
    try:
        controller.start_web(dict(language='en',provider='deepseek',model='deepseek-flash',translate=False,narrate=False,voice=0))
        assert controller.web_mode and controller.running
        assert controller.process.arguments()[-1]=='app.web_follow.desktop'
        payload=json.loads(controller.pending_command[7:])
        assert payload['translate'] is False and 'api_key' not in payload
        from app.web_follow.desktop import configuration
        parsed,_,_=configuration(controller.pending_command)
        assert parsed['caption_width']==92 and parsed['caption_font_size']==18
        controller.accept_event({'event':'web_service_ready','url':'http://127.0.0.1:1234/#private-test-only'})
        assert not any('private-test-only' in str(row) for row in controller.diagnostics)
    finally:controller.running=False;controller.cleanup_idle()


def test_current_gui_options_cross_the_real_startup_parser(app,monkeypatch,tmp_path):
    from app.web_follow.desktop import configuration
    model=tmp_path/'model';model.mkdir();(model/'model.bin').touch()
    monkeypatch.setattr(module.ASRConfig,'load',lambda *a,**k:SimpleNamespace(model=str(model)))
    class Job:
        name='Local\\ELT.Gui.test-only'
        def close(self):pass
    monkeypatch.setattr(module,'OwnerJob',Job)
    window=MainWindow();window.controller.process.start=lambda:None
    try:
        window.capture_mode.setCurrentIndex(window.capture_mode.findData('web'))
        window.web_captions.update(caption_width=65,caption_height=96,caption_font_size=14)
        window.translate_check.setChecked(False);window.speech_check.setChecked(False)
        window.start_capture()
        assert window.controller.running and window.controller.pending_command
        parsed,_,_=configuration(window.controller.pending_command)
        assert parsed['caption_width']==65 and parsed['caption_height']==96 and parsed['caption_font_size']==14
        assert not parsed['translate'] and not parsed['narrate']
    finally:window.controller.running=False;window.close();app.processEvents()


def test_source_only_web_mode_does_not_require_a_translation_model_or_key(app,monkeypatch):
    w=MainWindow();captured=[]
    try:
        w.capture_mode.setCurrentIndex(w.capture_mode.findData('web'))
        w.translate_check.setChecked(False);w.translation_model.setCurrentText('')
        monkeypatch.setattr(w.controller,'start_web',lambda options,*a:captured.append(options))
        w.start_capture()
        assert captured and captured[0]['translate'] is False and captured[0]['narrate'] is False
        assert captured[0]['model']=='deepseek-flash'
    finally:w.close();app.processEvents()


def test_web_preview_is_displayed_but_not_copied_to_diagnostics(app):
    controller=module.BackendController()
    try:
        controller.accept_event(dict(event='web_clock',preview_source='Private course preview',source_incomplete=True))
        assert controller.web_clock['preview_source']=='Private course preview'
        assert controller.course.incomplete
        assert 'Private course preview' not in str(controller.diagnostics)
    finally:controller.cleanup_idle()


def test_web_preparation_failure_is_not_labeled_as_still_loading(app):
    w=MainWindow()
    try:
        w.controller.web_mode=True
        w.backend_event(dict(event='web_clock',status='error',has_source=True,paired=True,
            prepared_until=10,position=12,skipped_windows=0,error='test-only audio discontinuity'))
        assert w.asr_status.text()=='预读已停止，请查看错误'
        assert w.notice.text()=='test-only audio discontinuity'
    finally:w.close();app.processEvents()


def test_web_ui_distinguishes_measured_sync_from_merely_prepared_subtitles(app):
    w=MainWindow()
    try:
        w.controller.web_mode=True
        w.backend_event(dict(event='web_clock',status='ready',has_source=True,paired=True,
            prepared_until=30,position=20,skipped_windows=0,error='',clock_calibrated=True,clock_offset_seconds=2.024))
        assert '已对时' in w.notice.text() and '提前 2.02 秒' in w.notice.text()
        w.backend_event(dict(event='web_clock',status='ready',has_source=True,paired=True,
            prepared_until=30,position=20,skipped_windows=0,error='',clock_calibrated=False,
            audio_alignment={'status':'inconclusive'}))
        assert '尚未完成声音对时' in w.notice.text() and '已对时' not in w.notice.text()
    finally:w.close();app.processEvents()


def test_closed_course_cannot_leave_old_voice_ready_or_calibration_notices(app):
    w=MainWindow()
    try:
        w.controller.web_mode=True
        w.backend_event(dict(event='web_clock',status='idle',has_source=False,paired=False,
            prepared_until=0,position=0,skipped_windows=0,error='',clock_calibrated=True,
            clock_offset_seconds=2,tts={'status':'ready'}))
        assert '等待课程视频' in w.speech_status.text() and '已就绪' not in w.speech_status.text()
        assert '打开课程窗口' in w.notice.text() and '已对时' not in w.notice.text()
    finally:w.close();app.processEvents()


def test_closed_controller_ignores_deferred_information_queries(app):
    from PySide6.QtCore import QTimer
    controller=module.BackendController();started=[]
    QTimer.singleShot(0,lambda:controller._task('late-query',lambda:started.append(True),lambda value:None,lambda error:None))
    controller.cleanup_idle();app.processEvents()
    assert controller.closed and not started and not controller.operations


def test_native_reading_changes_are_reflected_in_existing_saved_settings_without_starting_tts(app):
    w=MainWindow()
    try:
        w.capture_mode.setCurrentIndex(w.capture_mode.findData('web'))
        w.controller.web_mode=True
        w.backend_event(dict(event='web_clock',status='ready',has_source=True,paired=True,
            prepared_until=30,position=20,skipped_windows=0,error='',
            playback_options={'narrate':True,'volume':37,'base_speed':1.35,
                              'duck_source':False,'source_percent':45,
                              'speech_engine':'qwen','tts_model':'0.6B','tts_voice':'serena'}))
        saved=w.settings_snapshot()
        assert saved.speech_enabled and saved.speech_volume==37 and saved.web_base_speed==1.35
        assert saved.web_speech_engine=='qwen' and saved.speech_model_size=='0.6B' and saved.speech_voice=='serena'
        assert saved.speech_duck_source is False and saved.speech_source_percent==45
        assert not w.speech.active and w.speech.process is None and not w.controller.running
    finally:w.close();app.processEvents()


def test_web_qwen_uses_existing_voice_settings_without_starting_native_playback(app,monkeypatch,tmp_path):
    w=MainWindow();captured=[]
    try:
        runtime=tmp_path/'python.exe';runtime.touch();(tmp_path/'model.safetensors').touch()
        monkeypatch.setattr('app.speech.config.PYTHON',runtime)
        from app.speech.config import MODEL_PATHS
        monkeypatch.setitem(MODEL_PATHS,'1.7B',tmp_path)
        w.capture_mode.setCurrentIndex(w.capture_mode.findData('web'))
        w.speech_model.setCurrentIndex(w.speech_model.findData('1.7B'))
        w.speech_voice.setCurrentIndex(w.speech_voice.findData('aiden'))
        w.credential_status={'available':True};w.translate_check.setChecked(True);w.speech_check.setChecked(True)
        monkeypatch.setattr(w.controller,'start_web',lambda options,*a:captured.append(options))
        w.start_capture()
        assert captured[0]['speech_engine']=='qwen' and captured[0]['tts_model']=='1.7B' and captured[0]['tts_voice']=='aiden'
        assert not w.speech.active and w.speech.process is None
    finally:w.close();app.processEvents()


def test_internal_player_failure_stops_owned_web_backend(app,monkeypatch):
    w=MainWindow();seen=[]
    try:
        w.capture_mode.setCurrentIndex(w.capture_mode.findData('web'))
        monkeypatch.setattr(w,'show_problem',lambda message:seen.append(message))
        monkeypatch.setattr(w.controller,'stop',lambda:seen.append('stopped'))
        w.controller.running=True;w.controller.web_mode=True
        w.web_player.problem.emit('test-only failure')
        assert seen==['test-only failure','stopped']
    finally:w.controller.running=False;w.close();app.processEvents()


def test_local_file_entry_reuses_owned_player_without_starting_capture(app,monkeypatch):
    w=MainWindow();opened=[]
    try:
        monkeypatch.setattr(w.web_player,'open_file',lambda url='':opened.append(url))
        w.open_local_video()
        assert w.capture_mode.currentData()=='web' and w.web_player_choice.currentData()=='internal'
        assert opened==[''] and not w.controller.running and not w.web_local_button.isHidden()
        assert '本地' in w.capture_mode.currentText()
    finally:w.close();app.processEvents()


def test_player_start_request_uses_current_options_once_and_is_ignored_while_running_or_closing(app,monkeypatch):
    w=MainWindow();started=[]
    try:
        monkeypatch.setattr(w,'start_capture',lambda:started.append(True))
        w.web_start_requested();assert started==[True] and w.is_web_mode()
        w.controller.running=True;w.web_start_requested();assert len(started)==1
        w.controller.running=False;w.closing=True;w.web_start_requested();assert len(started)==1
    finally:w.closing=False;w.controller.running=False;w.close();app.processEvents()


def test_player_stdout_request_is_bounded_and_stale_process_output_is_ignored(app):
    from app.ui.web_player import WebPlayer
    player=WebPlayer();requests=[];player.follow_requested.connect(lambda:requests.append(True))
    process=SimpleNamespace(readAllStandardOutput=lambda:b'{"event":"player_follow_requested"}\n')
    player.process=process;player._read_output(process);assert requests==[True]
    other=SimpleNamespace(readAllStandardOutput=lambda:b'{"event":"player_follow_requested"}\n')
    player._read_output(other);assert len(requests)==1
    process.readAllStandardOutput=lambda:b'x'*32769;player._read_output(process);assert player.output==b''
    player.closing=True;process.readAllStandardOutput=other.readAllStandardOutput;player._read_output(process);assert len(requests)==1
    player.process=None
