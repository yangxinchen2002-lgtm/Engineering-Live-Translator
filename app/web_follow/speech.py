"""Opt-in offline SAPI speech files; never records the source audio."""
from pathlib import Path
import wave


def voices_for(language='zh') -> list[dict]:
    if language not in ('zh','en'):raise ValueError('invalid system speech language')
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    voice = tokens = token = None
    try:
        voice = win32com.client.Dispatch('SAPI.SpVoice')
        tokens = voice.GetVoices()
        result = []
        for i in range(tokens.Count):
            token = tokens.Item(i)
            languages = token.GetAttribute('Language').split(';')
            if any(int(x, 16) & 0x3ff == (4 if language=='zh' else 9) for x in languages):
                result.append(dict(id=i, label=token.GetDescription()))
        return result
    finally:
        token = tokens = voice = None
        pythoncom.CoUninitialize()


def chinese_voices() -> list[dict]:return voices_for('zh')


def synthesize(text: str, path: Path, voice_index: int,*,language='zh') -> float:
    if language not in ('zh','en'):raise ValueError('invalid system speech language')
    if not text.strip() or len(text) > 4096:
        raise ValueError('speech text outside bounds')
    if sum(p.stat().st_size for p in path.parent.glob('*.wav')) >= 16 * 1024 * 1024:
        raise ValueError('speech cache full')
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    voice = tokens = token = stream = None
    try:
        voice = win32com.client.Dispatch('SAPI.SpVoice')
        tokens = voice.GetVoices()
        token = tokens.Item(voice_index)
        if not any(int(x, 16) & 0x3ff == (4 if language=='zh' else 9) for x in token.GetAttribute('Language').split(';')):
            raise ValueError('selected speech voice does not match the translation language')
        voice.Voice = token
        stream = win32com.client.Dispatch('SAPI.SpFileStream')
        stream.Format.Type = 18  # SAFT16kHz16BitMono
        stream.Open(str(path), 3, False)  # SSFMCreateForWrite
        voice.AllowAudioOutputFormatChangesOnNextSet = False
        voice.AudioOutputStream = stream
        voice.Speak(text, 16)  # SVSFIsNotXML: source text must not become speech markup
        stream.Close()
    finally:
        stream = token = tokens = voice = None
        pythoncom.CoUninitialize()
    with wave.open(str(path), 'rb') as f:
        if f.getframerate() != 16000 or f.getnchannels() != 1 or f.getsampwidth() != 2 or not f.getnframes():
            raise ValueError('invalid synthesized speech format')
        return f.getnframes() / f.getframerate()
