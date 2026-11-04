"""Bounded, non-secret appearance preferences and logical-pixel window placement."""
from __future__ import annotations
from app.i18n import tr as _tr
from dataclasses import asdict,dataclass,fields,field
import json
import math
import os
from pathlib import Path
import re
import tempfile
from app.profile import profile_id
from app.languages import ASR_LANGUAGES
from app.audio.processes import SOURCE_LABELS
from app.translation.providers import PROVIDERS,provider_info,validate_model


@dataclass(frozen=True)
class UISettings:
    version:int=1
    ui_language:str='zh'
    target_language:str='zh'
    source:str='sessions'
    web_follow:bool=False
    web_lookahead:int=15
    web_voice:int=-1
    web_base_speed:float=1.
    web_player:str='internal'
    web_speech_engine:str='qwen'
    web_caption_width:int=92
    web_caption_height:int=180
    web_caption_font_size:int=18
    language:str='de'
    duration:int=3600
    translation_mode:str='sentence'
    translation_provider:str='deepseek'
    translation_models:dict[str,str]=field(default_factory=dict)
    save_transcripts:bool=False
    transcript_directory:str=''
    speech_enabled:bool=False
    speech_device:str='cuda'
    speech_model_size:str='0.6B'
    speech_voice:str='serena'
    speech_volume:int=80
    speech_speed:float=1.25
    speech_auto_catch_up:bool=True
    speech_catch_up_start_chars:int=80
    speech_catch_up_grace_seconds:int=5
    speech_duck_source:bool=True
    speech_source_percent:int=20
    auto_summary:bool=False
    font_family:str='Microsoft YaHei UI'
    font_size:int=21
    source_color:str='#ffffff'
    translation_color:str='#ffe09a'
    background_color:str='#10192c'
    opacity:int=86
    visible_segments:int=4
    focus_mode:bool=False
    focus_x:float=.5
    focus_y:float=.5
    overlay_width:int=900
    overlay_height:int=360
    glossary:str=''
    main_geometry:tuple[int,int,int,int]|None=None
    overlay_geometry:tuple[int,int,int,int]|None=None

    def validate(self):
        if self.ui_language not in ('zh','en') or self.target_language not in ('zh','en'):raise ValueError('invalid interface or target language')
        if type(self.version) is not int or self.version!=1:raise ValueError('unsupported UI settings version')
        if self.source not in SOURCE_LABELS or self.language not in ASR_LANGUAGES:raise ValueError('invalid source/language')
        if type(self.web_follow) is not bool:raise ValueError('invalid capture mode')
        if self.web_player not in ('internal','edge') or self.web_speech_engine not in ('qwen','system'):
            raise ValueError('invalid web player or speech engine')
        for name,low,high in (('web_caption_width',30,100),('web_caption_height',64,600),('web_caption_font_size',8,48)):
            if type(getattr(self,name)) is not int or not low<=getattr(self,name)<=high:raise ValueError('invalid video caption appearance')
        if type(self.web_lookahead) is not int or not 5<=self.web_lookahead<=30:raise ValueError('invalid web lookahead')
        if type(self.web_voice) is not int or not -1<=self.web_voice<=99:raise ValueError('invalid web voice')
        if type(self.web_base_speed) not in (int,float) or not math.isfinite(self.web_base_speed) or not 1<=self.web_base_speed<=2:
            raise ValueError('invalid web narration speed')
        if self.translation_mode not in ('preview','sentence'):raise ValueError('invalid translation mode')
        provider_info(self.translation_provider)
        if (not isinstance(self.translation_models,dict) or len(self.translation_models)>len(PROVIDERS)
                or self.translation_models.keys()-PROVIDERS.keys()):raise ValueError('invalid provider model preferences')
        for provider,model in self.translation_models.items():validate_model(provider,model)
        if type(self.save_transcripts) is not bool:raise ValueError('invalid transcript save preference')
        from app.speech.config import SpeechConfig
        SpeechConfig(self.speech_enabled,self.speech_device,self.speech_voice,self.speech_volume,
                     self.speech_speed,self.speech_auto_catch_up,self.speech_model_size,
                     self.speech_catch_up_start_chars,self.speech_catch_up_grace_seconds).validate()
        if type(self.speech_duck_source) is not bool:raise ValueError('invalid source duck setting')
        if type(self.speech_source_percent) is not int or not 10<=self.speech_source_percent<=100:
            raise ValueError('invalid source volume percentage')
        if type(self.auto_summary) is not bool:raise ValueError('invalid course summary preference')
        if not isinstance(self.transcript_directory,str) or len(self.transcript_directory)>4096 or '\x00' in self.transcript_directory:
            raise ValueError('invalid transcript directory')
        if type(self.focus_mode) is not bool:raise ValueError('invalid focus mode')
        for value in (self.focus_x,self.focus_y):
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1:
                raise ValueError('invalid focus position')
        if type(self.duration) is not int or self.duration not in (1800,3600,7200,28800):raise ValueError('invalid duration')
        for name,low,high in (('font_size',6,72),('opacity',35,95),('visible_segments',1,12),
                              ('overlay_width',280,8000),('overlay_height',120,8000)):
            if type(getattr(self,name)) is not int or not low<=getattr(self,name)<=high:raise ValueError('invalid appearance range')
        if not isinstance(self.font_family,str) or not 1<=len(self.font_family)<=128 or any(ord(c)<32 for c in self.font_family):
            raise ValueError('invalid font family')
        for value in (self.source_color,self.translation_color,self.background_color):
            if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError('invalid appearance color')
        if not isinstance(self.glossary,str) or len(self.glossary)>4096 or '\x00' in self.glossary:raise ValueError('invalid glossary path')
        for rect in (self.main_geometry,self.overlay_geometry):
            if rect is not None and (not isinstance(rect,(tuple,list)) or len(rect)!=4 or
                any(type(v) is not int or abs(v)>100000 for v in rect) or not 100<=rect[2]<=16000 or not 80<=rect[3]<=16000):
                raise ValueError('invalid window geometry')
        return self


def default_path() -> Path:
    if not os.environ.get('LOCALAPPDATA'):raise OSError('Windows local application data directory is unavailable')
    profile=profile_id()
    if profile:return Path(os.environ['LOCALAPPDATA'])/'ELT'/'profiles'/profile/'ui-settings.json'
    return Path(os.environ['LOCALAPPDATA'])/'ELT'/'ui-settings.json'


class PreferencesStore:
    def __init__(self,path:Path):self.path=Path(path);self.error=''

    def load(self) -> UISettings:
        try:
            with self.path.open('rb') as stream:raw=stream.read(16385)
            if len(raw)>16384:raise ValueError('settings file exceeds bound')
            data=json.loads(raw.decode('utf-8'))
            if not isinstance(data,dict) or data.keys()-{f.name for f in fields(UISettings)}:raise ValueError('unknown UI settings')
            for name in ('main_geometry','overlay_geometry'):
                if isinstance(data.get(name),list):data[name]=tuple(data[name])
            self.error='';return UISettings(**data).validate()
        except FileNotFoundError:return UISettings()
        except (OSError,ValueError,TypeError,UnicodeError):
            self.error=_tr('外观设置无法读取，已使用默认值；未自动覆盖原文件。');return UISettings()

    def save(self,settings:UISettings):
        settings.validate()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        name=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=self.path.parent,
                prefix='.elt-settings-',suffix='.tmp',delete=False) as output:
                name=Path(output.name);json.dump(asdict(settings),output,ensure_ascii=False,indent=2)
                output.flush();os.fsync(output.fileno())
            os.replace(name,self.path);self.error=''
        except OSError:
            self.error=_tr('外观设置保存失败，原文件未覆盖。');raise
        finally:
            if name and name.exists():name.unlink()


def place_window(rect, screens, minimum=(280,120)):
    """Clamp logical-pixel geometry onto an available monitor, including negatives."""
    if not screens:raise ValueError('no available screens')
    def intersection(screen):
        x,y,w,h=rect;sx,sy,sw,sh=screen
        return max(0,min(x+w,sx+sw)-max(x,sx))*max(0,min(y+h,sy+sh)-max(y,sy))
    screen=max(screens,key=intersection)
    if intersection(screen)==0:screen=screens[0]
    sx,sy,sw,sh=screen;x,y,w,h=rect
    w=min(max(w,minimum[0]),sw);h=min(max(h,minimum[1]),sh)
    return (max(sx,min(x,sx+sw-w)),max(sy,min(y,sy+sh-h)),w,h)
