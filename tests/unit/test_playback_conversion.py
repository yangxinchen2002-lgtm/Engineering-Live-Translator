import numpy as np
import pytest
from app.speech.playback import PlaybackConverter


@pytest.mark.parametrize('format,dtype',[('flt','<f4'),('s16','<i2'),('s32','<i4'),('u8','u1')])
def test_resampling_keeps_boundaries_duration_and_stereo(format,dtype):
    source=(np.sin(np.arange(24000)*2*np.pi*440/24000)*16000).astype('<i2').tobytes()
    whole=PlaybackConverter(24000,48000,2,format)
    expected=b''.join(whole.convert(source)+whole.convert(b''))
    chunked=PlaybackConverter(24000,48000,2,format)
    actual=b''.join(part for offset in range(0,len(source),770) for part in chunked.convert(source[offset:offset+770]))
    actual+=b''.join(chunked.convert(b''))
    assert actual==expected
    samples=np.frombuffer(actual,dtype=dtype).reshape(-1,2)
    assert samples.shape==(48000,2)
    assert np.isfinite(samples).all() and np.array_equal(samples[:,0],samples[:,1])
    assert np.ptp(samples[:,0])>0


def test_converter_rejects_incomplete_pcm():
    with pytest.raises(ValueError):PlaybackConverter(24000,48000,2,'flt').convert(b'x')


def test_normal_audio_end_and_streaming_underrun_are_not_playback_failures():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QAudio
    from app.ui.speech import SpeechController
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();problems=[];events=[]
    speech.problem.connect(problems.append);speech.diagnostic.connect(events.append)
    class Sink:
        def error(self):return QAudio.Error.UnderrunError
        def state(self):return QAudio.State.IdleState
        def processedUSecs(self):return 1000000
        def stop(self):pass
        def deleteLater(self):pass
    from collections import deque
    speech.sink=Sink();speech.audio=object()
    speech.current={'id':'1','raw':deque(),'samples':24000,'done':True};speech.samples=24000;speech.rendered_samples=24000
    speech._tick()
    assert speech.current and not problems  # A later streaming chunk may still arrive.
    speech.audio_done=True;speech._tick()
    assert speech.current is None and not problems
    assert events[-1]['event']=='speech_playback_finished'
    speech.close();app.processEvents()


@pytest.mark.parametrize('speed',[.8,1.25,1.5,1.8,2.,2.25,3.])
def test_faster_playback_shortens_duration_and_preserves_pitch(speed):
    source=(np.sin(np.arange(48000)*2*np.pi*440/24000)*16000).astype('<i2').tobytes()
    converter=PlaybackConverter(24000,48000,2,'flt',speed,dynamic=True)
    chunks=[]
    for offset in range(0,len(source),4800):chunks.extend(converter.convert(source[offset:offset+4800]))
    chunks.extend(converter.convert(b''))
    samples=np.frombuffer(b''.join(chunks),dtype='<f4').reshape(-1,2)
    assert abs(len(samples)/48000-2/speed)<.06
    assert np.isfinite(samples).all() and np.array_equal(samples[:,0],samples[:,1])
    frequencies=np.fft.rfftfreq(len(samples),1/48000)
    peak=frequencies[np.argmax(np.abs(np.fft.rfft(samples[:,0])))]
    assert abs(peak-440)<3


@pytest.mark.parametrize('changed_speed',[1.8,2.6,3.])
def test_tempo_can_change_in_one_stream_without_restarting_or_double_flushing(changed_speed):
    source=(np.sin(np.arange(96000)*2*np.pi*440/24000)*12000).astype('<i2').tobytes()
    converter=PlaybackConverter(24000,48000,2,'flt',1.,dynamic=True);chunks=[]
    for offset in range(0,len(source),4800):
        if offset==96000:converter.set_speed(changed_speed)
        chunks.extend(converter.convert(source[offset:offset+4800]))
    chunks.extend(converter.convert(b''))
    duration=len(b''.join(chunks))/8/48000
    assert abs(duration-(2+2/changed_speed))<.16
    with pytest.raises(ValueError):converter.convert(b'')


def test_continuous_catch_up_ramp_preserves_tone_and_audio_duration():
    from app.speech.pacing import CatchUpPacer
    rate=24000;pcm=(np.sin(np.arange(rate*8)*2*np.pi*440/rate)*12000).astype('<i2')
    converter=PlaybackConverter(rate,48000,1,'flt',2.,dynamic=True);pacer=CatchUpPacer(80,1)
    chunks=[];expected=0.
    for index in range(0,len(pcm),480):
        speed=pacer.update(300,2.,True,index*1_000_000_000//rate)
        converter.set_speed(speed);chunks.extend(converter.convert(pcm[index:index+480].tobytes()))
        expected+=480/rate/speed
    chunks.extend(converter.convert(b''));audio=np.frombuffer(b''.join(chunks),dtype='<f4')
    assert abs(len(audio)/48000-expected)<.12
    frequencies=np.fft.rfftfreq(len(audio),1/48000)
    assert abs(frequencies[np.argmax(np.abs(np.fft.rfft(audio)))]-440)<3
    assert np.isfinite(audio).all() and np.count_nonzero(np.abs(audio)>1e-5)/len(audio)>.95
