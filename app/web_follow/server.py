"""Loopback service for desktop-owned or explicit standalone web following."""
from __future__ import annotations
from app.i18n import tr as _tr

import argparse
from dataclasses import asdict,replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import re
import secrets
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit
import webbrowser

import httpx

from app.languages import ASR_LANGUAGES, LANGUAGE_LABELS
from app.translation.providers import PROVIDERS, validate_model
from .media import Source, byte_range
from .hls import HLS_MIME, fetch_manifest, rewrite_manifest
from .speech import chinese_voices,voices_for
from .timeline import Cue, Timeline, finite
from .worker import worker_main
from .bridge import BrowserBridge
from .paths import runtime_root,preferences_path
from .tts import settings as speech_settings

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CAPTION_FIELDS={'caption_width':(92,30,100),'caption_height':(180,64,600),'caption_font_size':(18,8,48)}
READING_FIELDS=frozenset({'narrate','volume','base_speed','speech_engine','tts_model','tts_voice','voice','duck_source','source_percent',*CAPTION_FIELDS})


def options_from(data: dict) -> dict:
    if not isinstance(data,dict):raise ValueError('invalid options')
    language, provider = data.get('language', 'de'), data.get('provider', 'deepseek')
    if language not in ASR_LANGUAGES or provider not in PROVIDERS:
        raise ValueError(_tr('语言或翻译服务无效'))
    target=data.get('target_language','zh');ui_language=data.get('ui_language','zh')
    if target not in ('zh','en') or ui_language not in ('zh','en'):raise ValueError(_tr('界面或翻译目标语言无效'))
    model = data.get('model', PROVIDERS[provider].models[0])
    validate_model(provider, model)
    translate, narrate = data.get('translate', False), data.get('narrate', False)
    if type(translate) is not bool or type(narrate) is not bool or narrate and not translate:
        raise ValueError(_tr('朗读需要先启用翻译'))
    voice = data.get('voice', 0)
    if type(voice) is not int or not 0 <= voice < 100:
        raise ValueError(_tr('音色编号无效'))
    volume=data.get('volume',80)
    if type(volume) is not int or not 0<=volume<=100:raise ValueError(_tr('朗读音量无效'))
    duck_source,source_percent=data.get('duck_source',True),data.get('source_percent',20)
    if type(duck_source) is not bool:raise ValueError(_tr('原声设置无效'))
    if type(source_percent) is not int or not 10<=source_percent<=100:raise ValueError(_tr('原声保留比例无效'))
    glossary=data.get('glossary','')
    if not isinstance(glossary,str) or len(glossary)>4096 or '\x00' in glossary:raise ValueError(_tr('术语表路径无效'))
    captions={}
    for key,(default,low,high) in CAPTION_FIELDS.items():
        value=data.get(key,default)
        if type(value) is not int or not low<=value<=high:raise ValueError(_tr('字幕大小或字号无效'))
        captions[key]=value
    return dict(language=language, provider=provider, model=model, translate=translate,target_language=target,ui_language=ui_language,
                narrate=narrate, voice=voice, lookahead=finite(data.get('lookahead', 15), 5, 30),
                volume=volume,base_speed=finite(data.get('base_speed',1),1,2),glossary=glossary,
                duck_source=duck_source,source_percent=source_percent,
                **captions,**speech_settings(data))


def production_busy() -> bool:
    import psutil
    own={p.pid for p in psutil.Process().children(recursive=True)}
    for process in psutil.process_iter(['name', 'cmdline']):
        try:
            if process.pid in own:continue
            if (process.info['name'] or '').lower() in ('python.exe', 'pythonw.exe'):
                if any(arg in ('app.ui.runner', 'app.speech.worker') for arg in process.info['cmdline'] or []):
                    return True
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return False


class Lab:
    def __init__(self):
        self.lock = threading.RLock()
        self.timeline = Timeline()
        self.source: Source | None = None
        self.status, self.error = 'idle', ''
        self.metadata, self.metrics = {}, {}
        self.busy = False
        self.ready = False
        self.last_seen = time.monotonic()
        self.process = self.tasks = self.output = self.generation = self.job = self.playhead = self.narration = self.reading_commands = None
        self.temp = None
        self.options = {}
        self.resources = {}
        self.clock_seq = -1
        self.session_id = ''
        self.phase_started = time.monotonic()
        self.preview = {}
        self.preview_generation = 0
        self.active_window = None
        self.last_catchup = 0.
        self.alignment=None
        self.clock_offset=0.;self.clock_calibrated=False;self.raw_position=0.;self.internal_player=False
        self.exit = threading.Event()
        self.thread = threading.Thread(target=self._pump, name='lookahead-controller', daemon=True)
        self.thread.start()

    def start(self, data, *, internal_player=False):
        source = Source.parse(data.get('source', ''))
        if not source.remote and data.get('source_identity') is not None and data['source_identity']!=list(source.local_identity):
            raise ValueError(_tr('本地视频已更改，请重新打开文件'))
        options = options_from(data)
        position = finite(data.get('position', 0), 0, 86399)
        options['start_position'] = position
        options['speech_revision']=0
        if production_busy():
            raise ValueError(_tr('请先停止其他 ELT 字幕和朗读会话，再启动网页预读，避免重复占用 GPU'))
        with self.lock:
            self._stop()
            self.timeline = Timeline(options['lookahead'])
            if position:
                self.timeline.seek(position)
            self.options, self.source = options, source
            self.internal_player=internal_player;self.raw_position=position
            self.clock_seq, self.session_id = -1, secrets.token_hex(8)
            self.status, self.error, self.ready, self.busy = 'loading', '', False, False
            self.metadata, self.metrics = {}, {}
            self.last_seen = time.monotonic()
            self.phase_started = self.last_seen
            context = mp.get_context('spawn')
            self.tasks, self.output = context.Queue(maxsize=1), context.Queue(maxsize=6)
            self.reading_commands=context.Queue(maxsize=1)
            self.generation = context.Value('q', self.timeline.generation)
            self.playhead = context.Value('d',position)
            self.narration=context.Value('b',options['narrate'])
            runtime = runtime_root()
            self.temp = tempfile.TemporaryDirectory(prefix='session-', dir=runtime)
            self.process = context.Process(target=worker_main, args=(source, options, self.tasks, self.output,
                self.generation, self.temp.name,self.playhead,self.narration,self.reading_commands), name='ELT-WebFollow')
            try:
                if os.name == 'nt':
                    import win32job
                    self.job = win32job.CreateJobObject(None, '')
                    info = win32job.QueryInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation)
                    info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                    win32job.SetInformationJobObject(self.job, win32job.JobObjectExtendedLimitInformation, info)
                self.process.start()
                if self.job is not None:
                    import win32api, win32job
                    handle = win32api.OpenProcess(0x0100 | 0x0001, False, self.process.pid)
                    try:
                        win32job.AssignProcessToJobObject(self.job, handle)
                    finally:
                        handle.Close()
            except BaseException:
                self._stop()
                raise

    def clock(self, data):
        position = finite(data.get('position'), 0, 86399)
        rate = finite(data.get('rate', 1), .25, 4)
        if type(data.get('paused')) is not bool or type(data.get('seek', False)) is not bool:
            raise ValueError('invalid player clock')
        with self.lock:
            self.last_seen = time.monotonic()
            if self.source is None:
                return
            if data.get('session_id', self.session_id) != self.session_id:
                return
            seq = data.get('sequence')
            if seq is not None:
                if type(seq) is not int or not 0 <= seq <= 10**9:
                    raise ValueError('invalid clock sequence')
                if seq <= self.clock_seq:
                    return
                self.clock_seq = seq
            self.raw_position=position
            if self.alignment:self.alignment.observe(position,data['paused'],rate,data.get('seek',False))
            # The audio decoder uses source time; the original player remains
            # untouched. Its clock is mapped only after an actual audio match.
            position=max(0,min(86399,position+self.clock_offset))
            if self.status=='error':
                # Preserve the real failure; a moving video is not a recovery.
                self.timeline.position,self.timeline.rate,self.timeline.paused=position,rate,data['paused']
                if self.playhead is not None:self.playhead.value=position
                return
            if data.get('seek'):
                self.timeline.seek(position)
                self.preview.clear()
                self.generation.value = self.timeline.generation
                self.status = 'preparing'
            elif abs(position - self.timeline.position) > 3:
                # A missed seeking event must never display stale subtitles at a new time.
                self.timeline.seek(position)
                self.preview.clear()
                self.generation.value = self.timeline.generation
                self.status = 'preparing'
            elif (self.ready and position > (self.active_window[1] if self.busy and self.active_window else self.timeline.prepared_until) + 1
                  and time.monotonic()-self.last_catchup>5):
                skipped=max(0,position-self.timeline.prepared_until)
                self.metrics['expired_windows_skipped']=self.metrics.get('expired_windows_skipped',0)+1
                self.metrics['skipped_media_seconds']=self.metrics.get('skipped_media_seconds',0)+skipped
                self.metrics['source_complete']=False
                self.timeline.seek(position);self.preview.clear()
                self.generation.value=self.timeline.generation;self.last_catchup=time.monotonic()
                self.status='preparing'
            self.timeline.position, self.timeline.rate, self.timeline.paused = position, rate, data['paused']
            if self.playhead is not None:self.playhead.value=position

    def apply_alignment(self,result):
        if self.clock_calibrated or result.get('status')!='measured':return False
        if result.get('confirmations')!=2 or result.get('correlation',0)<.55 or result.get('peak_margin',0)<.12:return False
        try:offset=finite(result.get('offset_seconds'),-4,4)
        except ValueError:
            self.metrics['audio_alignment_invalid']=True;return False
        self.clock_offset=offset if abs(offset)>=.15 else 0.
        self.clock_calibrated=True
        self.metrics.update(clock_calibrated=True,clock_offset_seconds=self.clock_offset,
                            calibration_player_position=self.raw_position)
        self.timeline.position=max(0,min(86399,self.raw_position+self.clock_offset))
        if self.playhead is not None:self.playhead.value=self.timeline.position
        return True

    def update_playback(self,data):
        allowed=READING_FIELDS
        if not isinstance(data,dict) or data.keys()-allowed:raise ValueError('invalid reading settings')
        with self.lock:
            was_enabled=self.options.get('narrate',False)
            proposed={**self.options,**data}
            checked=options_from(proposed)
            voice_changed=any(k in data and data[k]!=self.options.get(k) for k in ('speech_engine','tts_model','tts_voice','voice'))
            revision=self.options.get('speech_revision',0)+int(voice_changed)
            for key in allowed:self.options[key]=checked[key]
            self.options['speech_revision']=revision
            self.options['playback_revision']=self.options.get('playback_revision',0)+1
            if self.narration is not None:self.narration.value=checked['narrate']
            if voice_changed:
                self.timeline.cues=[replace(c,speech='',speech_seconds=0,speech_error='') for c in self.timeline.cues]
                for c in self.preview.values():c.update(speech='',speech_seconds=0,speech_error='')
            if self.reading_commands is not None and (voice_changed or checked['narrate'] and not was_enabled):
                pending=[asdict(c) for c in self.timeline.cues if c.end>self.timeline.position and c.translation and not c.speech][:8]
                command={'options':dict(self.options),'generation':self.timeline.generation,'cues':pending}
                try:self.reading_commands.put_nowait(command)
                except queue.Full:
                    try:self.reading_commands.get(timeout=.05)
                    except queue.Empty:pass
                    try:self.reading_commands.put_nowait(command)
                    except queue.Full:raise ValueError(_tr('朗读设置忙，请稍后重试'))

    def player_diagnostics(self,data):
        if not isinstance(data,dict):return
        safe={}
        for key in ('audio_requests','audio_fetched','audio_fetch_failed','playing','ended','blocked','audio_errors'):
            value=data.get(key,0)
            if type(value) is int and 0<=value<=10**8:safe[key]=value
        with self.lock:self.metrics['playback']=safe

    def state(self):
        with self.lock:
            snapshot=self.timeline.snapshot()
            merged={c['id']:c for c in snapshot['cues']}
            if self.preview_generation==self.timeline.generation:
                merged.update(self.preview)
            snapshot['cues']=sorted(merged.values(),key=lambda c:c['start'])[-96:]
            pending=[c['start'] for c in snapshot['cues'] if c['end']>self.timeline.position
                     and c.get('asr_confirmed') and not c['translation']]
            translated_until=min(pending) if pending else self.timeline.prepared_until
            # Export presentation times in the browser's coordinate system.
            # Cue/ASR objects retain their original source timestamps internally.
            offset=self.clock_offset
            source_position=snapshot['position'];source_prepared=snapshot['prepared_until']
            snapshot['position']=self.raw_position if self.clock_calibrated else source_position
            snapshot['prepared_until']=max(0,source_prepared-offset)
            if snapshot['duration'] is not None:snapshot['duration']=max(0,snapshot['duration']-offset)
            snapshot['cues']=[{**c,'start':max(0,c['start']-offset),'end':max(0,c['end']-offset)}
                              for c in snapshot['cues'] if c['end']-offset>0]
            return dict(**snapshot, status=self.status, error=self.error, session_id=self.session_id,
                        metadata=self.metadata, metrics=self.metrics, worker_busy=self.busy,
                        start_position=self.options.get('start_position',0),
                        source_ahead_seconds=max(0,self.timeline.prepared_until-self.timeline.position),
                        translation_ahead_seconds=max(0,min(self.timeline.prepared_until,translated_until)-self.timeline.position),
                        clock_offset_seconds=offset,clock_calibrated=self.clock_calibrated,
                        source_position=source_position,source_prepared_until=source_prepared,
                        playback={'base_speed':self.options.get('base_speed',1),'volume':self.options.get('volume',80),
                                  'ui_language':self.options.get('ui_language','zh'),'target_language':self.options.get('target_language','zh'),
                                  'duck_source':self.options.get('duck_source',True),'source_percent':self.options.get('source_percent',20),
                                  'narrate':self.options.get('narrate',False),'speech_engine':self.options.get('speech_engine','system'),
                                  'tts_model':self.options.get('tts_model','0.6B'),'tts_voice':self.options.get('tts_voice','serena'),
                                  'voice':self.options.get('voice',0),'speech_revision':self.options.get('speech_revision',0),
                                  'playback_revision':self.options.get('playback_revision',0),
                                  **{k:self.options.get(k,v[0]) for k,v in CAPTION_FIELDS.items()}},
                        worker_pid=self.process.pid if self.process else None, has_source=self.source is not None,
                        source_kind='local_file' if self.source and not self.source.remote else 'web')

    def _recover_worker(self, exitcode):
        """One visible recovery per source session; never controls a browser/video."""
        if self.source is None or self.metrics.get('worker_restarts',0)>=1:
            return False
        previous=dict(self.metrics);session=self.session_id;generation=self.timeline.generation
        internal_player=self.internal_player
        data={**self.options,'source':self.source.value,'position':self.raw_position}
        try:
            self.start(data,internal_player=internal_player)
            self.session_id=session
            self.timeline.generation=generation+1
            self.generation.value=self.timeline.generation
            self.metrics.update({k:v for k,v in previous.items() if k in ('expired_windows_skipped','skipped_media_seconds')})
            self.metrics.update(worker_restarts=previous.get('worker_restarts',0)+1,
                last_worker_exitcode=exitcode,source_complete=False,previous_worker_usage=previous.get('usage'))
            return True
        except Exception:
            return False

    def _pump(self):
        while not self.exit.wait(.08):
            with self.lock:
                if self.process is None:
                    continue
                if self.alignment:
                    measured=self.alignment.snapshot();self.metrics['audio_alignment']=measured
                    self.apply_alignment(measured)
                if time.monotonic() - self.last_seen > 120:
                    self._stop()
                    continue
                if (not self.ready or self.busy) and time.monotonic() - self.phase_started > 120:
                    self._stop()
                    self.error, self.status = _tr('预读工作超过 120 秒，已停止网页跟随并释放模型'), 'error'
                    continue
                try:
                    while True:
                        event = self.output.get_nowait()
                        kind = event['type']
                        if kind == 'metadata':
                            self.metadata = {k: v for k, v in event.items() if k != 'type'}
                            self.timeline.duration = event['duration']
                            if self.internal_player and self.source.remote and self.alignment is None:
                                from .alignment import AudioAlignment,own_player
                                try:target=own_player()
                                except Exception as error:
                                    target=None;self.metrics['audio_alignment']={'status':'inconclusive','reason':type(error).__name__}
                                helper=ROOT/'native/build/Release/elt_capture.exe'
                                if target and helper.is_file():self.alignment=AudioAlignment(self.source,target,helper)
                                else:self.metrics.setdefault('audio_alignment',{'status':'inconclusive','reason':'active native audio session or capture helper unavailable'})
                            if self.timeline.position >= self.timeline.duration:
                                self.error, self.status = _tr('起播位置超过视频时长'), 'error'
                        elif kind == 'ready':
                            self.ready = True
                            self.status = 'preparing'
                            self.metrics.update({k: v for k, v in event.items() if k != 'type'})
                        elif kind == 'decoding' and event['generation']==self.timeline.generation:
                            self.active_window=(event['begin'],event['end'])
                        elif kind == 'preview' and event['generation']==self.timeline.generation:
                            self.preview_generation=event['generation']
                            self.preview={c['id']:c for c in event['cues']}
                            self.metrics['asr_prepared_until']=event['end']
                        elif kind == 'cue' and event['generation']==self.timeline.generation:
                            self.apply_cue(event['cue'])
                            self.update_usage(event.get('usage'))
                        elif kind == 'translation_status':
                            self.update_usage(event.get('usage'))
                            self.metrics.update({k:v for k,v in event.items() if k not in ('type','usage')})
                        elif kind == 'tts_status' and event.get('speech_revision',0)==self.options.get('speech_revision',0):
                            self.metrics['tts']={k:v for k,v in event.items() if k!='type'}
                        elif kind == 'speech_cue' and event['generation']==self.timeline.generation and event.get('speech_revision',0)==self.options.get('speech_revision',0):
                            self.apply_speech(event['cue'],event.get('speech_revision',0))
                            if event.get('tts_seconds') is not None:self.metrics['tts_last_seconds']=event['tts_seconds']
                        elif kind in ('batch', 'cancelled'):
                            self.busy = False
                            self.update_usage(event.get('usage'))
                            if kind == 'batch' and self.timeline.commit(event['generation'], event['begin'], event['end'],
                                                                       [self.speech_result(Cue(**c)) for c in event['cues']]):
                                self.status = 'ready'
                                self.preview.clear()
                                repairs=event.get('audio',{}).get('rounding_repaired_samples',0)
                                self.metrics['timestamp_repair_samples']=self.metrics.get('timestamp_repair_samples',0)+repairs
                                self.metrics['timestamp_repair_windows']=self.metrics.get('timestamp_repair_windows',0)+int(repairs>0)
                                self.metrics.update({k: v for k, v in event.items()
                                                     if k not in ('type', 'generation', 'begin', 'end', 'cues','usage')})
                                self._prune_speech()
                        elif kind == 'error':
                            self.error, self.status, self.busy = event['message'], 'error', False
                            self.metrics.setdefault('first_error',event['message'])
                            self.metrics['source_complete']=False
                except queue.Empty:
                    pass
                except Exception as e:
                    self.error, self.status = str(e) if type(e) is ValueError else type(e).__name__, 'error'
                if self.process.exitcode is not None and self.status != 'error':
                    code=self.process.exitcode
                    if self._recover_worker(code):continue
                    self.error, self.status = f"{_tr('网页工作进程已退出（')}{code}{_tr('）；请重新开始 ELT，视频不受控制')}", 'error'
                    self.metrics['last_worker_exitcode']=code
                    self.metrics['source_complete']=False
                if self.status == 'error':
                    continue
                if self.ready and not self.busy:
                    window = self.timeline.plan()
                    if window:
                        try:
                            self.tasks.put_nowait((self.timeline.generation, *window))
                            self.busy = True
                            self.active_window=window
                            self.phase_started = time.monotonic()
                        except queue.Full:
                            self.error, self.status = _tr('网页任务队列异常：未提交音频窗口'), 'error'

    def speech_result(self,cue):
        previous=self.preview.get(cue.id)
        if previous and previous.get('source')==cue.source:
            if not cue.translation and previous.get('translation'):
                cue=replace(cue,translation=previous['translation'],translation_error='')
            elif not cue.translation_error and not cue.translation:
                cue=replace(cue,translation_error=previous.get('translation_error',''))
            if previous.get('translation')==cue.translation:
                cue=replace(cue,**{k:previous[k] for k in ('speech','speech_seconds','speech_error')})
        return cue

    def update_usage(self,value):
        if value is not None and value.get('usage_revision',0)>=self.metrics.get('usage',{}).get('usage_revision',0):
            self.metrics['usage']=value

    def apply_cue(self,value):
        cue=Cue(**value)
        for index,previous in enumerate(self.timeline.cues):
            if previous.id==cue.id and previous.source==cue.source:
                if previous.translation and not cue.translation:cue=replace(cue,translation=previous.translation,translation_error='')
                if previous.translation==cue.translation and previous.speech and not cue.speech:
                    cue=replace(cue,speech=previous.speech,speech_seconds=previous.speech_seconds,speech_error=previous.speech_error)
                self.timeline.cues[index]=cue;return
        previous=self.preview.get(cue.id)
        if previous and previous['source']==cue.source:self.preview[cue.id]=asdict(cue)

    def apply_speech(self,value,revision=None):
        if revision is not None and revision!=self.options.get('speech_revision',0):return False
        fields={k:value[k] for k in ('speech','speech_seconds','speech_error')}
        previous=self.preview.get(value['id'])
        if previous and previous.get('translation')==value['translation']:previous.update(fields)
        self.timeline.cues=[replace(c,**fields) if c.id==value['id'] and c.translation==value['translation'] else c
                            for c in self.timeline.cues]
        return True

    def _prune_speech(self):
        if self.temp is None:
            return
        keep = {c.speech for c in self.timeline.cues if c.speech} | {c['speech'] for c in self.preview.values() if c.get('speech')}
        for p in Path(self.temp.name).glob('*.wav'):
            if p.name not in keep and time.time()-p.stat().st_mtime>30:
                try:
                    p.unlink()
                except PermissionError:
                    pass  # A browser response still owns this file; next pass retries.

    def _stop(self):
        if self.alignment:self.alignment.close();self.alignment=None
        self.clock_offset=0.;self.clock_calibrated=False;self.raw_position=0.;self.internal_player=False
        if self.narration is not None:self.narration.value=False
        if self.generation is not None:
            self.generation.value += 1
        if self.process is not None:
            if self.process.pid:
                try:
                    self.tasks.put_nowait(None)
                except queue.Full:
                    pass
                self.process.join(timeout=1)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(timeout=3)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join(timeout=3)
                if self.process.is_alive():
                    raise RuntimeError(_tr('网页进程未能退出，临时数据未清理'))
            # Preserve reported accounting from a request cancelled by STOP.
            try:
                for _ in range(6):
                    event=self.output.get_nowait()
                    usage=event.get('usage')
                    if usage and usage.get('usage_revision',0)>=self.metrics.get('usage',{}).get('usage_revision',0):
                        self.metrics['usage']=usage
            except queue.Empty:pass
            self.process.close()
        if self.job is not None:
            self.job.Close()
        for q in (self.tasks, self.output,self.reading_commands):
            if q is not None:
                q.cancel_join_thread()
                q.close()
        if self.temp is not None:
            self.temp.cleanup()
        self.process = self.tasks = self.output = self.job = self.temp = self.generation = self.playhead = self.narration = self.reading_commands = None
        self.source = None
        self.session_id=secrets.token_hex(8)
        self.resources.clear()
        self.preview.clear();self.preview_generation=0;self.active_window=None
        self.ready = self.busy = False
        self.status = 'idle'
        self.timeline = Timeline()

    def stop(self):
        with self.lock:
            self._stop()

    def close(self):
        self.exit.set()
        self.thread.join(timeout=5)
        self.stop()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, lab, preferences_path: Path | None = None, desktop_options: dict | None = None):
        self.lab, self.token = lab, secrets.token_urlsafe(32)
        self.preferences_path=preferences_path
        self.desktop_options=options_from(desktop_options) if desktop_options is not None else None
        if self.desktop_options is not None:self.lab.options=dict(self.desktop_options)
        self.desktop_stopping=False
        self.bridge=BrowserBridge(lab,preferences_path)
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(('127.0.0.1', 0), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.closed = threading.Event()
        self.watch = threading.Thread(target=self._watch, name='lookahead-page-lifetime', daemon=True)
        self.watch.start()

    def _watch(self):
        while not self.closed.wait(1):
            self.bridge.expire()
            if time.monotonic() - self.lab.last_seen > (180 if self.bridge.token else 60):
                self.shutdown()
                return

    def server_close(self):
        self.closed.set()
        self.watch.join(timeout=2)
        super().server_close()

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, *args):
        pass  # No signed media URLs, source paths, keys or transcripts in request logs.

    def headers_for(self, status, mime, size=None, extra=()):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        if size is not None:
            self.send_header('Content-Length', str(size))
        for key, value in extra:
            self.send_header(key, str(value))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        origin=self.headers.get('Origin','')
        if re.fullmatch(r'chrome-extension://[a-p]{32}',origin):
            self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Vary','Origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; media-src 'self' blob:; worker-src 'self' blob:; frame-ancestors 'none'; object-src 'none'")
        self.end_headers()

    def json(self, value, status=200):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.headers_for(status, 'application/json; charset=utf-8', len(raw))
        self.wfile.write(raw)

    def authorized(self, media=False):
        host = urlsplit(self.server.origin).netloc
        if self.headers.get('Host') != host or self.headers.get('Origin', self.server.origin) != self.server.origin:
            return False
        # Native clients can authenticate media with a header. HTML media
        # elements cannot set that header and use the same token in the URL.
        supplied = self.headers.get('X-ELT-Lab-Token')
        if supplied is None:
            supplied = parse_qs(urlsplit(self.path).query).get('token', [''])[0] if media else ''
        return secrets.compare_digest(supplied, self.server.token)

    def do_GET(self):
        try:
            self._get()
        except (BrokenPipeError, ConnectionError, TimeoutError):
            pass

    def _get(self):
        path = urlsplit(self.path).path
        if path.startswith('/bridge/'):
            if not self.bridge_authorized():self.json({'error':'forbidden'},403);return
            if path=='/bridge/status':
                self.json(self.server.bridge.status());return
            if path=='/bridge/settings':
                self.json(self.server.bridge.settings());return
            try:
                data={'owner':parse_qs(urlsplit(self.path).query).get('owner',[''])[0]}
                self.server.bridge.check(data)
                if path.startswith('/bridge/audio/'):
                    self.speech_file(path.removeprefix('/bridge/audio/'))
                else:self.json({'error':'not found'},404)
            except ValueError:self.json({'error':'observer session expired'},409)
            return
        static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript'),
                  '/sync.mjs': ('sync.mjs', 'text/javascript'),
                  '/vendor/hls.light.min.js': ('vendor/hls.light.min.js', 'text/javascript'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        static['/follow-core.js']=('../extension/core.js','text/javascript')
        static['/subtitle-layout.js']=('../extension/layout.js','text/javascript')
        static['/connect.js']=('connect.js','text/javascript')
        static['/ui-locale.js']=('ui-locale.js','text/javascript; charset=utf-8')
        if self.server.desktop_options is not None:static['/']=('connect.html','text/html; charset=utf-8')
        if path in static:
            name, mime = static[path]
            raw = (HERE / 'web' / name).read_bytes()
            if name.endswith('.html'):
                from app.i18n import get_language
                language=(self.server.desktop_options or {}).get('ui_language',get_language())
                raw=raw.replace(b'<html lang="zh-CN">',f'<html lang="{language}" data-elt-ui-language="{language}">'.encode())
            self.headers_for(200, mime, len(raw))
            self.wfile.write(raw)
            return
        if not self.authorized(media=path.startswith(('/media', '/speech/', '/hls/'))):
            self.json({'error': _tr('网页连接已失效，请在 ELT 主程序重新启动网页跟随')}, 403)
            return
        if path == '/api/state':
            self.json(self.server.lab.state())
        elif path == '/api/bridge-status':
            self.json(self.server.bridge.status())
        elif path == '/api/settings':
            defaults=dict(self.server.desktop_options or {})
            try:
                if not defaults and self.server.preferences_path is not None:
                    defaults=options_from(json.loads(self.server.preferences_path.read_text(encoding='utf-8')))
            except (OSError,ValueError,TypeError):pass
            self.json(dict(languages={**LANGUAGE_LABELS, 'auto': _tr('自动检测')}, voices=chinese_voices() if defaults.get('target_language','zh')=='zh' else voices_for(defaults['target_language']),
                           providers={k: dict(label=v.label, models=v.models) for k, v in PROVIDERS.items()},defaults=defaults))
        elif path == '/media':
            with self.server.lab.lock:
                source = self.server.lab.source
                session = self.server.lab.session_id
            if source is None:
                self.json({'error': 'no source'}, 404)
            elif source.hls:
                self.manifest(source.value, session)
            elif source.remote:
                self.proxy(source)
            else:
                self.file(Path(source.value), source.mime)
        elif path.startswith('/hls/'):
            with self.server.lab.lock:
                url = self.server.lab.resources.get(path.removeprefix('/hls/'))
                session = self.server.lab.session_id
            if url is None:
                self.json({'error':'media resource expired'}, 404)
            elif urlsplit(url).path.lower().endswith('.m3u8'):
                self.manifest(url, session)
            else:
                self.proxy(Source(url, True, 'application/octet-stream'))
        elif path.startswith('/speech/'):
            self.speech_file(path.removeprefix('/speech/'))
        else:
            self.json({'error': 'not found'}, 404)

    def speech_file(self,name):
        with self.server.lab.lock:
            temp=self.server.lab.temp
            allowed={c.speech for c in self.server.lab.timeline.cues if c.speech} | {c['speech'] for c in self.server.lab.preview.values() if c.get('speech')}
            file=Path(temp.name)/name if temp and name in allowed and re.fullmatch(r'[0-9-]+\.wav',name) else None
        if file and file.is_file():self.file(file,'audio/wav')
        else:self.json({'error':'speech not available'},404)

    def bridge_authorized(self):
        return (self.headers.get('Host')==urlsplit(self.server.origin).netloc and self.server.bridge.authorized(
            self.headers.get('X-ELT-Extension-Id',''),self.headers.get('X-ELT-Bridge-Token',''),self.headers.get('Origin','')))

    def reject_post(self):
        # Drain only a bounded body before closing. Leaving even a tiny POST
        # body unread can reset the Windows socket before the 403 is received.
        try:
            length=int(self.headers.get('Content-Length','0'))
            if 0<length<=32768:self.rfile.read(length)
        except (ValueError,OSError):
            self.close_connection=True
        self.json({'error':'forbidden'},403)

    def do_OPTIONS(self):
        origin=self.headers.get('Origin','')
        if not re.fullmatch(r'chrome-extension://[a-p]{32}',origin):self.json({'error':'forbidden'},403);return
        self.headers_for(204,'text/plain',0,[('Access-Control-Allow-Methods','GET, POST, OPTIONS'),
            ('Access-Control-Allow-Headers','Content-Type, X-ELT-Lab-Token, X-ELT-Extension-Id, X-ELT-Bridge-Token')])

    def bridge_post(self):
        path=urlsplit(self.path).path
        pair=path=='/bridge/pair'
        valid=self.headers.get('Host')==urlsplit(self.server.origin).netloc
        if pair:
            extension=self.headers.get('X-ELT-Extension-Id','')
            valid=valid and self.headers.get('Origin','') in ('',f'chrome-extension://{extension}')
            valid=valid and secrets.compare_digest(self.headers.get('X-ELT-Lab-Token',''),self.server.token)
        else:valid=valid and self.bridge_authorized()
        if not valid:self.reject_post();return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=32768:raise ValueError('invalid body size')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise ValueError('invalid body')
            if self.server.desktop_stopping:
                self.json({'stopped':True});return
            if pair:result=self.server.bridge.pair(extension,self.server.desktop_options or options_from(data.get('options',{})))
            elif path=='/bridge/ping':
                with self.server.lab.lock:self.server.lab.last_seen=time.monotonic()
                result=self.server.bridge.status()
            elif path=='/bridge/start':result=self.server.bridge.start(data)
            elif path=='/bridge/clock':result=self.server.bridge.clock(data)
            elif path=='/bridge/playback':result=self.server.bridge.playback(data)
            elif path=='/bridge/stop':self.server.bridge.stop(data);result={'stopped':True}
            else:self.json({'error':'not found'},404);return
            self.json(result)
        except (ValueError,OSError) as e:self.json({'error':str(e) if type(e) is ValueError else type(e).__name__},400)
        except Exception as e:self.json({'error':type(e).__name__},500)

    def file(self, path, mime):
        try:
            f = path.open('rb')
        except OSError:
            self.json({'error': 'media not available'}, 404)
            return
        with f:
            size = os.fstat(f.fileno()).st_size
            try:
                start, end = byte_range(self.headers.get('Range'), size)
            except ValueError:
                self.headers_for(416, mime, 0, [('Content-Range', f'bytes */{size}')])
                return
            partial = self.headers.get('Range') is not None
            extra = [('Accept-Ranges', 'bytes')]
            if partial:
                extra.append(('Content-Range', f'bytes {start}-{end}/{size}'))
            self.headers_for(206 if partial else 200, mime, end - start + 1, extra)
            f.seek(start)
            remaining = end - start + 1
            while remaining:
                raw = f.read(min(65536, remaining))
                if not raw:
                    break
                self.wfile.write(raw)
                remaining -= len(raw)

    def proxy(self, source):
        headers = {'Accept-Encoding': 'identity'}
        if self.headers.get('Range'):
            headers['Range'] = self.headers['Range']
        try:
            with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
                with client.stream('GET', source.value, headers=headers) as response:
                    if response.status_code not in (200, 206, 416):
                        self.json({'error': _tr('媒体链接不可读取')}, 502)
                        return
                    extra = [(k, response.headers[k]) for k in ('content-range', 'accept-ranges') if k in response.headers]
                    self.headers_for(response.status_code, response.headers.get('content-type', source.mime),
                                     response.headers.get('content-length'), extra)
                    for raw in response.iter_raw(65536):
                        self.wfile.write(raw)
        except httpx.HTTPError:
            self.close_connection = True

    def manifest(self, url, session):
        try:
            text = fetch_manifest(url)
            def register(value):
                import hashlib
                identity = hashlib.sha256((session + value).encode()).hexdigest()[:32]
                with self.server.lab.lock:
                    if session != self.server.lab.session_id or self.server.lab.source is None:
                        raise ValueError(_tr('播放来源已更换，请重新准备'))
                    resources = self.server.lab.resources
                    if identity not in resources and len(resources) >= 8192:
                        raise ValueError(_tr('HLS 分片数量超过处理容量'))
                    resources[identity] = value
                return '/hls/' + identity + '?token=' + self.server.token
            raw = rewrite_manifest(text, url, register).encode()
            self.headers_for(200, HLS_MIME, len(raw))
            self.wfile.write(raw)
        except ValueError as e:
            self.json({'error':str(e)}, 422)
        except httpx.HTTPError:
            self.json({'error':_tr('HLS 请求失败，请检查网络或播放链接有效期')}, 502)

    def do_POST(self):
        if urlsplit(self.path).path.startswith('/bridge/'):
            self.bridge_post();return
        if not self.authorized():
            self.reject_post()
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 32768:
                raise ValueError(_tr('请求过大'))
            data = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(data, dict):
                raise ValueError(_tr('请求格式无效'))
            path = urlsplit(self.path).path
            if path == '/api/start':
                internal=(self.server.desktop_options is not None and self.headers.get('User-Agent','').startswith('python-httpx/'))
                self.server.lab.start(data,internal_player=internal)
            elif path == '/api/clock':
                self.server.lab.clock(data)
                self.server.lab.player_diagnostics(data.get('playback',{}))
            elif path == '/api/playback':
                defaults=self.server.desktop_options or self.server.lab.options
                proposed=options_from({**defaults,**data})
                if data.keys()-READING_FIELDS:raise ValueError('invalid reading settings')
                with self.server.lab.lock:
                    if not self.server.lab.options:self.server.lab.options=dict(proposed)
                    self.server.lab.update_playback(data)
                if self.server.desktop_options is not None:self.server.desktop_options.update({k:proposed[k] for k in data})
            elif path == '/api/ping':
                with self.server.lab.lock:
                    self.server.lab.last_seen = time.monotonic()
            elif path in ('/api/stop', '/api/quit'):
                self.server.lab.stop()
                if path == '/api/quit':
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.json({'error': 'not found'}, 404)
                return
            self.json(self.server.lab.state())
        except (BrokenPipeError, ConnectionError, TimeoutError):
            return  # Browser closed/replaced a request; no capture or subtitle was dropped.
        except (ValueError, OSError) as e:
            self.json({'error': str(e) if type(e) is ValueError else type(e).__name__}, 400)
        except Exception as e:
            self.json({'error': _tr('网页跟随启动失败：') + type(e).__name__}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open', action='store_true', help='open the independent local web player')
    parser.add_argument('--edge', action='store_true', help='open the experiment settings in Microsoft Edge')
    parser.add_argument('--ready-file', type=Path, help='explicit automation output; contains only the local page URL')
    args = parser.parse_args()
    lab = Lab()
    server = Server(lab,preferences_path=preferences_path())
    url = server.origin + '/#' + server.token
    if args.ready_file:
        args.ready_file.write_text(json.dumps(dict(url=url, pid=os.getpid())), encoding='utf-8')
    if args.open:
        if args.edge and os.name=='nt':os.startfile('microsoft-edge:'+url)
        else:webbrowser.open(url)
    if not args.open:
        print('Independent lookahead lab:', url, flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        lab.close()


if __name__ == '__main__':
    mp.freeze_support()
    main()
