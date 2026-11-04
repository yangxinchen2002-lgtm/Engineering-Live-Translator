import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import numpy as np
import pytest
from app.speech.config import LECTURE_VOICE,SpeechConfig,model_speaker
from app.speech.pauses import PauseCompactor
from app.speech.playback import PlaybackConverter


def test_long_near_silence_is_bounded_and_voiced_samples_are_unchanged():
    rate=24000
    voiced=(np.sin(np.arange(4800)*2*np.pi*180/rate)*5000).astype('<i2').tobytes()
    short=b'\0\0'*4800;long=b'\0\0'*24000
    source=voiced+short+voiced+long+voiced
    expected=voiced+short+voiced+b'\0\0'*7680+voiced
    for width in (2,770,4800,len(source)):
        compact=PauseCompactor(rate)
        output=b''.join(compact.convert(source[i:i+width]) for i in range(0,len(source),width))+compact.flush()
        assert output==expected and compact.removed_samples==16320
        assert not compact.held and not compact.partial


def test_quiet_speech_above_threshold_and_short_pauses_are_kept():
    # -54 dBFS RMS is quiet, but must remain untouched even for a long run.
    source=np.full(24000,65,dtype='<i2').tobytes()+b'\0\0'*9360
    compact=PauseCompactor(24000)
    assert compact.convert(source)+compact.flush()==source
    with pytest.raises(ValueError):compact.convert(b'\0\0')


def test_partial_final_frame_survives_and_long_silent_tail_is_compacted():
    for source,expected in ((b'\0\0'*24001,b'\0\0'*7680),
                            (b'\0\0'*9001,b'\0\0'*9001),
                            (np.full(1001,120,dtype='<i2').tobytes(),np.full(1001,120,dtype='<i2').tobytes())):
        compact=PauseCompactor(24000)
        assert compact.convert(source)+compact.flush()==expected


def test_compaction_and_tempo_flush_only_once_and_preserve_output_pitch():
    rate=24000
    voice=(np.sin(np.arange(rate)*2*np.pi*180/rate)*10000).astype('<i2').tobytes()
    source=voice+b'\0\0'*rate+voice
    converter=PlaybackConverter(rate,rate,1,'s16',1.25,compact_pauses=True,dynamic=True)
    output=b''.join(c for offset in range(0,len(source),770) for c in converter.convert(source[offset:offset+770]))
    output+=b''.join(converter.convert(b''))
    wave=np.frombuffer(output,dtype='<i2')
    assert abs(len(wave)/rate-2.32/1.25)<.06
    peak=np.fft.rfftfreq(len(wave),1/rate)[np.argmax(abs(np.fft.rfft(wave)))]
    assert abs(peak-180)<3
    with pytest.raises(ValueError):converter.convert(b'')


def test_lecture_alias_is_resolved_on_cpu_and_gpu_without_changing_text():
    from app.speech.runtime import SpeechEngine
    text='请注意，可惜，这个方法不适用。'
    assert model_speaker(LECTURE_VOICE)=='aiden'
    assert model_speaker('ryan')=='ryan'
    SpeechConfig(voice=LECTURE_VOICE).validate()
    with pytest.raises(ValueError):model_speaker('missing')
    for fast in (False,True):
        calls=[]
        class Model:
            def generate_custom_voice(self,**options):
                calls.append(options);return [np.ones(2000,dtype=np.float32)],24000
            def generate_custom_voice_streaming(self,**options):
                calls.append(options);yield np.ones(2000,dtype=np.float32),24000,{}
        engine=SpeechEngine.__new__(SpeechEngine);engine.model=Model();engine.fast=fast;engine.model_size='0.6B';engine.language='zh'
        assert sum(len(chunk) for chunk,rate in engine.generate(text,LECTURE_VOICE))==2000
        assert calls[0]['text']==text and calls[0]['speaker']=='aiden' and 'instruct' not in calls[0]


def test_lecture_preset_and_device_restore_and_can_change_without_a_model(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.ui.preferences import PreferencesStore,UISettings
    from app.ui.window import MainWindow
    monkeypatch.setattr('app.ui.controller.manage_credential',lambda action:{'available':False,'source':'unavailable'})
    app=QApplication.instance() or QApplication([])
    store=PreferencesStore(tmp_path/'settings.json')
    store.save(replace(UISettings(),speech_voice=LECTURE_VOICE,speech_device='cpu'))
    window=MainWindow(preferences=store);app.processEvents()
    assert window.speech_voice.currentData()==LECTURE_VOICE
    assert window.speech_device.currentData()=='cpu' and window.speech.process is None
    assert window.settings_snapshot().speech_voice==LECTURE_VOICE
    window.close();app.processEvents()


@pytest.mark.parametrize('fast',[False,True])
def test_17b_lecture_instruction_reaches_both_backends_without_changing_words(fast):
    from app.speech.runtime import SpeechEngine
    from app.speech.config import LECTURE_INSTRUCTION,MODEL_PATHS
    calls=[]
    class Model:
        def generate_custom_voice(self,**options):
            calls.append(options);return [np.ones(2000,dtype=np.float32)],24000
        def generate_custom_voice_streaming(self,**options):
            calls.append(options);yield np.ones(2000,dtype=np.float32),24000,{}
    engine=SpeechEngine.__new__(SpeechEngine);engine.model=Model();engine.fast=fast;engine.model_size='1.7B';engine.language='zh'
    text='请注意，这个结论有一个前提。可惜，这个方法不适用。'
    list(engine.generate(text,LECTURE_VOICE))
    assert calls[0]['instruct']==LECTURE_INSTRUCTION and calls[0]['text']==text
    assert calls[0]['speaker']=='aiden'
    assert SpeechConfig(model_size='1.7B').validate().model_path==MODEL_PATHS['1.7B']
    with pytest.raises(ValueError):SpeechConfig(model_size='other').validate()


def test_model_switch_resets_only_speech_and_saves_new_model_choice(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.ui.preferences import PreferencesStore,UISettings
    from app.ui.window import MainWindow
    monkeypatch.setattr('app.ui.controller.manage_credential',lambda action:{'available':False,'source':'unavailable'})
    app=QApplication.instance() or QApplication([])
    store=PreferencesStore(tmp_path/'settings.json')
    store.save(replace(UISettings(),speech_voice=LECTURE_VOICE,speech_device='cpu',speech_model_size='1.7B'))
    window=MainWindow(preferences=store);app.processEvents()
    assert window.speech_model.currentData()=='1.7B' and window.speech.config.model_size=='1.7B'
    assert window.speech_device.currentData()=='cpu' and window.speech.process is None
    calls=[];monkeypatch.setattr(window.speech,'clear',lambda message:calls.append(message))
    window.speech.active=True
    window.speech_model.setCurrentIndex(window.speech_model.findData('0.6B'))
    assert calls and window.speech.config.model_size=='0.6B'
    assert window.speech_device.currentData()=='cpu' and not window.controller.running
    assert window.settings_snapshot().speech_model_size=='0.6B'
    window.speech.active=False;window.close();app.processEvents()


def test_ready_message_cannot_claim_a_different_model_size():
    from PySide6.QtWidgets import QApplication
    from app.ui.speech import SpeechController
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.config=SpeechConfig(model_size='1.7B')
    with pytest.raises(ValueError):speech._event({'event':'speech_ready','device':'cuda','model_size':'0.6B'})
    speech.close();app.processEvents()
