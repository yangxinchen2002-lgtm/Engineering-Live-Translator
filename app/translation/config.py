from __future__ import annotations
from dataclasses import dataclass, fields
import math
from pathlib import Path
import tomllib
from urllib.parse import urlsplit
from .providers import provider_info,validate_model

ROOT = Path(__file__).resolve().parents[2]
TRANSLATION_MODES = ('preview','sentence')


@dataclass(frozen=True)
class TranslationConfig:
    provider: str = 'deepseek'
    base_url: str = 'https://api.deepseek.com'
    model: str = 'deepseek-flash'
    mode: str = 'preview'
    glossary: str = str(ROOT/'terminology/engineering.json')
    domain: str = ''
    concurrency: int = 2
    queue_capacity: int = 16
    request_timeout_seconds: float = 12.0
    connect_timeout_seconds: float = 3.0
    max_retries: int = 2
    retry_delay_seconds: float = .5
    task_ttl_seconds: float = 24.0
    finish_grace_seconds: float = 15.0
    preview_min_words: int = 4
    preview_interval_seconds: float = 1.5
    stream_emit_interval_seconds: float = .1
    max_source_words: int = 40
    max_source_chars: int = 800
    max_output_chars: int = 4096
    max_tokens: int = 1024
    context_count: int = 5
    context_chars: int = 2800
    max_prompt_chars: int = 6000
    glossary_count: int = 12
    glossary_chars: int = 2400
    record_capacity: int = 128
    history_queue_capacity: int = 64
    target_language: str = 'zh'

    def validate(self) -> TranslationConfig:
        from app.languages import TARGET_LANGUAGES
        if self.target_language not in TARGET_LANGUAGES:raise ValueError('translation target must be zh or en')
        info=provider_info(self.provider)
        url = urlsplit(self.base_url)
        allowed=('', '/v1') if self.provider=='deepseek' else (urlsplit(info.base_url).path,)
        if (url.scheme != 'https' or url.hostname != urlsplit(info.base_url).hostname or url.username or url.password
                or url.port is not None or url.query or url.fragment or url.path.rstrip('/') not in allowed):
            raise ValueError('translation base_url must be the selected provider official HTTPS endpoint')
        validate_model(self.provider,self.model)
        if self.mode not in TRANSLATION_MODES:
            raise ValueError('translation mode must be preview or sentence')
        bounds = {'concurrency':(1,4),'queue_capacity':(1,64),'max_retries':(0,3),
                  'preview_min_words':(1,20),'max_source_words':(4,100),'max_source_chars':(80,1600),
                  'max_output_chars':(128,16384),'max_tokens':(64,4096),'context_count':(0,5),
                  'context_chars':(0,6000),'max_prompt_chars':(2048,24000),'glossary_count':(0,24),'glossary_chars':(0,4000),
                  'record_capacity':(16,512),'history_queue_capacity':(1,256)}
        for name,(low,high) in bounds.items():
            value = getattr(self,name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f'{name} must be an integer in {low}..{high}')
        for name in ('request_timeout_seconds','connect_timeout_seconds','retry_delay_seconds',
                     'task_ttl_seconds','finish_grace_seconds','preview_interval_seconds','stream_emit_interval_seconds'):
            value = getattr(self,name)
            if type(value) not in (int,float) or not math.isfinite(value) or not 0 < value <= 60:
                raise ValueError(f'{name} must be finite and in (0,60]')
        if self.connect_timeout_seconds > self.request_timeout_seconds:
            raise ValueError('connect timeout exceeds request deadline')
        if not isinstance(self.glossary,str) or not isinstance(self.domain,str) or len(self.domain)>80:
            raise ValueError('invalid glossary path/domain')
        return self

    @classmethod
    def load(cls,path:Path|None=None) -> TranslationConfig:
        data = tomllib.loads(path.read_text(encoding='utf-8')).get('translation',{}) if path else {}
        if not isinstance(data,dict) or data.keys()-{f.name for f in fields(cls)}:
            raise ValueError('unknown translation settings; API keys must not be stored in TOML')
        if 'glossary' in data:
            data['glossary'] = str(((path.resolve().parent if path else ROOT)/data['glossary']).resolve())
        return cls(**data).validate()
