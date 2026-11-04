from dataclasses import dataclass
from pathlib import Path
import re
import math

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT/'models/Qwen3-TTS-12Hz-0.6B-CustomVoice'
MODEL_PATHS = {'0.6B':MODEL,'1.7B':ROOT/'models/Qwen3-TTS-12Hz-1.7B-CustomVoice'}
MODEL_SIZES = (('0.6B','0.6B · 快速朗读'),('1.7B','1.7B · 平稳讲课'))
LECTURE_INSTRUCTION = '以平稳、客观的课堂讲解口吻朗读，语速均匀，情绪克制，停顿简短自然。“请注意”和“可惜”只作普通逻辑提示，保持平常语气。'
BUNDLED_PYTHON = ROOT/'runtime/tts/python.exe'
PYTHON = BUNDLED_PYTHON if BUNDLED_PYTHON.is_file() else ROOT/'.venv-tts/Scripts/python.exe'
VOICES = (
    ('lecture_male', '讲课男声 · Aiden（试用）'),
    ('serena', 'Serena · 温和女声'), ('vivian', 'Vivian · 明亮女声'),
    ('uncle_fu', 'Uncle Fu · 沉稳男声'), ('dylan', 'Dylan · 北京口音男声'),
    ('eric', 'Eric · 四川口音男声'), ('ryan', 'Ryan · 英语男声'),
    ('aiden', 'Aiden · 英语男声'), ('ono_anna', 'Anna · 日语女声'),
    ('sohee', 'Sohee · 韩语女声'),
)
LECTURE_VOICE = 'lecture_male'
PREVIEW_TEXT = '请注意，这里的矩阵必须是方阵。可惜，这个方法只适用于线性系统。现在先说明条件，再按顺序介绍计算步骤。'
PREVIEW_TEXT_EN = 'Please note that this matrix must be square. This method applies only to linear systems. We will explain the assumptions before the calculation steps.'
LECTURE_INSTRUCTION_EN = 'Read as a calm, clear university lecturer. Keep a steady pace, restrained emotion, and short natural pauses. Preserve technical terms and mathematical meaning.'


def model_speaker(voice):
    """Application presets must resolve to one of Qwen's actual speaker IDs."""
    if voice not in {v[0] for v in VOICES}:raise ValueError('invalid speech voice')
    return 'aiden' if voice==LECTURE_VOICE else voice


@dataclass(frozen=True)
class SpeechConfig:
    enabled: bool = False
    device: str = 'cuda'
    voice: str = 'serena'
    volume: int = 80
    speed: float = 1.25
    auto_catch_up: bool = True
    model_size: str = '0.6B'
    catch_up_start_chars: int = 80
    catch_up_grace_seconds: int = 5
    engine: str = 'qwen'
    system_voice: int = -1
    language: str = 'zh'

    @property
    def model_path(self):
        return MODEL_PATHS[self.model_size]

    def validate(self):
        if self.language not in ('zh','en'):raise ValueError('invalid speech language')
        if self.engine not in ('qwen','system') or type(self.system_voice) is not int or not -1<=self.system_voice<100:
            raise ValueError('invalid speech engine/system voice')
        if type(self.enabled) is not bool or self.device not in ('cuda','cpu'):
            raise ValueError('invalid speech device/enabled setting')
        if self.voice not in {v[0] for v in VOICES} or type(self.volume) is not int or not 0<=self.volume<=100:
            raise ValueError('invalid speech voice/volume')
        if type(self.speed) not in (float,int) or not math.isfinite(self.speed) or not .8<=self.speed<=2:
            raise ValueError('invalid speech speed')
        if type(self.auto_catch_up) is not bool:raise ValueError('invalid speech catch-up setting')
        if self.model_size not in MODEL_PATHS:raise ValueError('invalid speech model size')
        if type(self.catch_up_start_chars) is not int or not 20<=self.catch_up_start_chars<=1000:
            raise ValueError('catch-up threshold must be 20..1000 characters')
        if type(self.catch_up_grace_seconds) is not int or not 1<=self.catch_up_grace_seconds<=30:
            raise ValueError('catch-up grace period must be 1..30 seconds')
        return self


def split_for_speech(text, limit=160):
    """Keep every character; prefer sentence/phrase boundaries for bounded utterances."""
    if not isinstance(text,str) or not 1<=limit<=400 or len(text)>16384:
        raise ValueError('invalid speech text')
    parts=[]; pending=''
    for piece in re.findall(r'[^。！？!?；;，,\n]+[。！？!?；;，,\n]*|[。！？!?；;，,\n]+', text):
        if pending and len(pending)+len(piece)>limit:
            parts.append(pending);pending=''
        while len(piece)>limit:
            if pending:parts.append(pending);pending=''
            boundary=piece.rfind(' ',0,limit+1)
            end=boundary+1 if boundary>limit//2 else limit
            parts.append(piece[:end]);piece=piece[end:]
        pending+=piece
    if pending:parts.append(pending)
    if ''.join(parts)!=text:raise ValueError('speech segmentation changed the text')
    return [p for p in parts if p.strip()]
