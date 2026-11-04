import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from app.ui.window import MainWindow
from app.ui.preferences import UISettings,PreferencesStore
from app.speech.config import SpeechConfig


@pytest.fixture
def app(monkeypatch):
    from app.ui.controller import BackendController
    monkeypatch.setattr(BackendController,'refresh_processes',lambda self:None)
    monkeypatch.setattr(BackendController,'refresh_web_voices',lambda self:None)
    return QApplication.instance() or QApplication([])


def test_model_picker_unifies_system_and_qwen_and_preserves_qwen_choice(app):
    window=MainWindow();app.processEvents()
    try:
        window.speech_model.setCurrentIndex(window.speech_model.findData('1.7B'))
        window.speech_voice.setCurrentIndex(window.speech_voice.findData('lecture_male'))
        window.speech_model.setCurrentIndex(window.speech_model.findData('system'))
        window.web_voices_ready([{'id':7,'label':'系统中文音色'}])
        assert window.web_speech_engine.currentData()=='system' and window.web_voice.currentData()==7
        assert window.speech_voice.isHidden() and not window.web_voice.isHidden() and not window.speech_device.isEnabled()
        config=window.speech_config();assert config.engine=='system' and config.system_voice==7 and config.device=='cpu'
        assert not window.speech.process and not window.controller.running
        saved=window.settings_snapshot().validate();assert saved.speech_model_size=='1.7B' and saved.speech_voice=='lecture_male'
        window.speech_model.setCurrentIndex(window.speech_model.findData('1.7B'))
        assert window.speech_config().engine=='qwen' and window.speech_config().voice=='lecture_male'
        assert window.speech_device.isEnabled() and not window.speech_voice.isHidden()
    finally:window.close();app.processEvents()


def test_saved_system_choice_and_caption_size_restore_without_loading_a_model(app,tmp_path):
    store=PreferencesStore(tmp_path/'settings.json')
    store.save(replace(UISettings(),web_speech_engine='system',web_voice=7,speech_model_size='1.7B',
        web_caption_width=64,web_caption_height=96,web_caption_font_size=14))
    window=MainWindow(preferences=store);app.processEvents()
    try:
        window.web_voices_ready([{'id':7,'label':'系统中文音色'}])
        assert window.speech_model.currentData()=='system' and window.speech_config().system_voice==7
        assert window.web_captions=={'caption_width':64,'caption_height':96,'caption_font_size':14}
        assert window.settings_snapshot().web_caption_font_size==14 and not window.speech.process
    finally:window.close();app.processEvents()


def test_system_web_start_uses_real_voice_index_and_never_a_system_qwen_model(app,monkeypatch):
    window=MainWindow();app.processEvents();calls=[]
    try:
        window.capture_mode.setCurrentIndex(window.capture_mode.findData('web'))
        window.speech_model.setCurrentIndex(window.speech_model.findData('system'))
        window.web_voices_ready([{'id':7,'label':'系统中文音色'}])
        window.credential_status={'available':True};window.translate_check.setChecked(True);window.speech_check.setChecked(True)
        monkeypatch.setattr(window.controller,'start_web',lambda options,*args:calls.append(options))
        window.start_capture()
        assert calls[0]['speech_engine']=='system' and calls[0]['voice']==7
        assert calls[0]['tts_model'] in ('0.6B','1.7B') and not window.speech.process
    finally:window.close();app.processEvents()


def test_system_engine_streams_pcm_without_file_or_gpu(monkeypatch):
    from app.speech.system import SystemSpeechEngine
    from app.speech import system
    from app.web_follow import speech
    monkeypatch.setattr(speech,'chinese_voices',lambda:[{'id':7,'label':'test only'}])
    def synthesize(text,index):
        assert index==7 and text=='测试。';return b'\x00\x40'*17000
    monkeypatch.setattr(system,'synthesize_pcm',synthesize)
    engine=SystemSpeechEngine(7);chunks=list(engine.generate('测试。'))
    assert engine.info['engine']=='windows-sapi' and engine.info['device']=='cpu'
    assert sum(len(audio) for audio,rate in chunks)==17000 and all(rate==16000 for audio,rate in chunks)
    assert np.allclose(chunks[0][0],.5)
    with pytest.raises(ValueError):SystemSpeechEngine(99)
    with pytest.raises(ValueError):replace(SpeechConfig(),engine='missing').validate()
