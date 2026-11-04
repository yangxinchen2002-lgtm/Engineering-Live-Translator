"""Explicitly paired browser observer. Owns no browser control API."""
from __future__ import annotations
from app.i18n import tr as _tr
import re
import secrets
import time
import json
from pathlib import Path
from urllib.parse import urlsplit

MEDIA_HOSTS = {'edge.live.rbg.tum.de', 'video.opencast.tum.de'}


def validate_media(value):
    if not isinstance(value,str) or len(value)>4096:
        raise ValueError('invalid media URL')
    url=urlsplit(value)
    if (url.scheme!='https' or url.hostname not in MEDIA_HOSTS or url.username or url.password
            or not url.path.lower().endswith(('.mp4','.m3u8'))):
        raise ValueError(_tr('网页跟随仅支持指定 TUM 站点的实际媒体'))
    return value


class BrowserBridge:
    def __init__(self,lab,settings_path: Path | None = None):
        self.lab=lab;self.extension='';self.token='';self.owner='';self.session='';self.options={}
        self.last_clock=0.
        self.settings_path=settings_path

    def pair(self,extension,options):
        if not re.fullmatch('[a-p]{32}',extension or ''):
            raise ValueError('invalid browser extension identity')
        if self.owner:self.lab.stop()
        if self.settings_path is not None:
            self.settings_path.parent.mkdir(exist_ok=True)
            self.settings_path.write_text(json.dumps(options,ensure_ascii=False),encoding='utf-8')
        self.extension=extension;self.token=secrets.token_urlsafe(32);self.options=options
        if self.lab is not None:
            with self.lab.lock:
                if self.lab.source is None:self.lab.options=dict(options)
        self.owner=self.session=''
        return {'token':self.token,'options':options}

    def authorized(self,extension,token,origin):
        return (bool(self.token) and extension==self.extension and secrets.compare_digest(token,self.token)
                and origin in ('',f'chrome-extension://{extension}'))

    def start(self,data):
        owner=data.get('owner','')
        if not isinstance(owner,str) or not re.fullmatch('[A-Za-z0-9-]{16,80}',owner):
            raise ValueError('invalid observer session')
        settings={**self.options,'source':validate_media(data.get('source')),'position':data.get('position',0)}
        if data.get('language'):settings['language']=data['language']
        self.lab.start(settings)
        self.owner=owner;self.session=self.lab.session_id
        self.last_clock=time.monotonic()
        return self.lab.state()

    def check(self,data):
        if data.get('owner')!=self.owner or not self.owner or self.session!=self.lab.session_id:
            raise ValueError(_tr('网页跟随会话已停止，请重新开始'))

    def clock(self,data):
        self.check(data)
        self.last_clock=time.monotonic()
        self.lab.clock({**data,'session_id':self.session})
        return self.lab.state()

    def stop(self,data):
        self.check(data);self.lab.stop();self.owner=self.session=''

    def status(self):
        return {'paired':bool(self.token),'active':bool(self.owner and self.session==self.lab.session_id),
                'mode':'follow_clock_optional_volume'}

    def settings(self):
        from .speech import chinese_voices,voices_for
        from app.speech.config import VOICES
        from .server import READING_FIELDS
        with self.lab.lock:
            active=bool(self.owner and self.session==self.lab.session_id)
            values=self.lab.state()['playback'] if active or self.lab.source is None else {k:self.options[k] for k in READING_FIELDS if k in self.options}
            return dict(playback=values,translate=bool(self.options.get('translate')),language=self.lab.options.get('language',self.options.get('language','de')) if active else self.options.get('language','de'),
                        session_id=self.session if active else '',ui_language=self.options.get('ui_language','zh'),target_language=self.options.get('target_language','zh'),
                        voices=chinese_voices() if self.options.get('target_language','zh')=='zh' else voices_for(self.options['target_language']),
                        tts_voices=[dict(id=key,label=label) for key,label in VOICES])

    def playback(self,data):
        from .server import READING_FIELDS,options_from
        changes=data.get('options')
        if not isinstance(changes,dict) or changes.keys()-READING_FIELDS:raise ValueError('invalid reading settings')
        warning=''
        with self.lab.lock:
            active=bool(self.owner and self.session==self.lab.session_id)
            if active:
                self.check(data)
                if data.get('session_id')!=self.session:raise ValueError(_tr('字幕会话已改变，请重新打开扩展设置'))
            elif self.lab.source is not None or data.get('owner'):
                raise ValueError(_tr('当前字幕会话已改变，请重新打开扩展设置'))
            checked=options_from({**self.options,**changes})
            self.lab.update_playback(changes)
            self.options.update({key:checked[key] for key in changes})
            if self.settings_path is not None:
                try:
                    self.settings_path.parent.mkdir(exist_ok=True)
                    temporary=self.settings_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(self.options,ensure_ascii=False,allow_nan=False),encoding='utf-8')
                    temporary.replace(self.settings_path)
                except OSError:warning=_tr('设置已应用，但网页偏好保存失败。')
            result=dict(playback=self.lab.state()['playback'],session_id=self.session if active else '')
        return {**result,'warning':warning}

    def expire(self):
        with self.lab.lock:
            if self.owner and self.session==self.lab.session_id and time.monotonic()-self.last_clock>120:
                self.lab.stop();self.owner=self.session=''
