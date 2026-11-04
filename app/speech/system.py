"""Offline Windows voices on the existing bounded PCM worker protocol."""
from app.i18n import tr as _tr
import time


def synthesize_pcm(text,voice_index,language='zh'):
    if language not in ('zh','en'):raise ValueError('invalid system speech language')
    if not isinstance(text,str) or not text.strip() or len(text)>400:raise ValueError('system speech text outside bounds')
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize();voice=tokens=token=stream=None
    try:
        voice=win32com.client.Dispatch('SAPI.SpVoice');tokens=voice.GetVoices();token=tokens.Item(voice_index)
        if not any(int(x,16)&0x3ff==(4 if language=='zh' else 9) for x in token.GetAttribute('Language').split(';')):
            raise ValueError(_tr('所选系统音色与译文语言不匹配'))
        voice.Voice=token;stream=win32com.client.Dispatch('SAPI.SpMemoryStream');stream.Format.Type=18
        voice.AllowAudioOutputFormatChangesOnNextSet=False;voice.AudioOutputStream=stream
        voice.Speak(text,16)  # SVSFIsNotXML; no sound-device output or temporary file.
        pcm=bytes(stream.GetData())
        if not pcm or len(pcm)%2 or len(pcm)>8*1024*1024:raise ValueError('invalid system speech PCM')
        return pcm
    finally:
        stream=token=tokens=voice=None;pythoncom.CoUninitialize()


class SystemSpeechEngine:
    def __init__(self,voice_index,model_size='0.6B',*,language='zh'):
        started=time.perf_counter()
        from app.web_follow.speech import chinese_voices,voices_for
        if voice_index not in {v['id'] for v in (chinese_voices() if language=='zh' else voices_for(language))}:
            raise ValueError(_tr('未找到目标语言的 Windows 系统音色，请检查系统语音包'))
        self.voice_index=voice_index;self.language=language
        self.info=dict(device='cpu',model_size=model_size,engine='windows-sapi',language=language,load_seconds=time.perf_counter()-started)

    def generate(self,text,voice=None,*,seed=None):
        import numpy as np
        pcm=synthesize_pcm(text,self.voice_index) if self.language=='zh' else synthesize_pcm(text,self.voice_index,self.language)
        for begin in range(0,len(pcm),32000):
            yield np.frombuffer(pcm[begin:begin+32000],dtype='<i2').astype(np.float32)/32768,16000
