"""Bounded local Qwen file generation, independent of ASR and cloud requests."""
from __future__ import annotations
from app.i18n import tr as _tr
import base64
from dataclasses import asdict,replace
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import wave

from app.speech.config import PYTHON,ROOT,SpeechConfig,split_for_speech
from app.ui.lifetime import OwnerJob,JOB_ENV


class CueExpired(InterruptedError):
    """The completed request was discarded; its model/protocol remain usable."""


class TTSProcessError(RuntimeError):
    def __init__(self,code,stage):
        super().__init__('local TTS process failed');self.code=code;self.stage=stage


def settings(data):
    engine=data.get('speech_engine','system')
    if engine not in ('system','qwen'):raise ValueError(_tr('网页朗读引擎无效'))
    config=SpeechConfig(device=data.get('tts_device','cuda'),model_size=data.get('tts_model','0.6B'),
                        voice=data.get('tts_voice','serena')).validate()
    return dict(speech_engine=engine,tts_device=config.device,tts_model=config.model_size,tts_voice=config.voice)


class QwenFiles:
    """Use the existing deployed TTS worker; never play audio from this process."""
    def __init__(self,options,status=lambda **kw:None):
        config=SpeechConfig(device=options['tts_device'],model_size=options['tts_model'],voice=options['tts_voice'],language=options.get('target_language','zh')).validate()
        if not PYTHON.is_file() or not (config.model_path/'model.safetensors').is_file():
            raise ValueError(_tr('所选本地 TTS 模型或运行环境尚未安装'))
        self.options=options;self.events=queue.Queue(maxsize=32);self.closed=threading.Event();self.ready=False;self.serial=0
        self.job=OwnerJob();self.process=None;self.threads=[];self.status=status
        try:
            env={**os.environ,JOB_ENV:self.job.name,'PYTHONUTF8':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
            self.process=subprocess.Popen([str(PYTHON),'-u','-B','-m','app.speech.worker','--device',config.device,
                                          '--model-size',config.model_size,'--language',config.language],cwd=ROOT,env=env,stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
            self.status(status='loading',engine='qwen',device=config.device,model=config.model_size,pid=self.process.pid)
            self.threads=[threading.Thread(target=self._read,daemon=True),threading.Thread(target=self._drain,daemon=True)]
            for thread in self.threads:thread.start()
        except BaseException:self.close();raise

    def _put(self,value):
        while not self.closed.is_set():
            try:self.events.put(value,timeout=.1);return
            except queue.Full:continue

    def _read(self):
        try:
            while not self.closed.is_set():
                line=self.process.stdout.readline(262145)
                if not line:break
                if len(line)>262144:raise ValueError('TTS output limit')
                self._put(json.loads(line))
        except (ValueError,OSError):pass
        finally:self._put({'event':'eof'})

    def _drain(self):
        # Library output may contain text. Drain without copying it to diagnostics.
        try:
            while not self.closed.is_set() and self.process.stderr.read(4096):pass
        except OSError:pass

    def _next(self,deadline,stale):
        while True:
            if self.closed.is_set() or stale():raise InterruptedError('TTS cancelled')
            if time.monotonic()>deadline:raise TimeoutError('TTS preparation timeout')
            try:event=self.events.get(timeout=.1)
            except queue.Empty:continue
            if event['event']=='speech_error':raise TTSProcessError(event.get('code','worker_error'),event.get('stage','worker'))
            if event['event']=='eof':raise TTSProcessError('worker_exited','worker')
            return event

    def wait_ready(self,cancelled):
        if not self.ready:
            deadline=time.monotonic()+180
            while True:
                event=self._next(deadline,cancelled)
                if event['event']=='speech_ready':
                    if event['device']!=self.options['tts_device'] or event.get('model_size')!=self.options['tts_model']:
                        raise ValueError('TTS model/device mismatch')
                    self.ready=True;self.status(status='ready',engine='qwen',device=event['device'],
                        model=event['model_size'],pid=self.process.pid);break

    def synthesize(self,text,path,stale,cancelled=lambda:False):
        self.wait_ready(cancelled)
        if stale():raise CueExpired('sentence expired before synthesis')
        if len(text)>4096:raise ValueError('TTS text limit')
        if sum(p.stat().st_size for p in path.parent.glob('*.wav'))>=16*1024*1024:raise ValueError('speech cache full')
        temporary=path.with_suffix('.part');count=0;rate=None;deadline=time.monotonic()+45;expired=False
        try:
            with wave.open(str(temporary),'wb') as output:
                output.setnchannels(1);output.setsampwidth(2);output.setframerate(24000)
                for part in split_for_speech(text,350):
                    if stale():raise CueExpired('sentence expired before next part')
                    self.serial+=1;identity=str(self.serial)
                    data=dict(id=identity,text=part,voice=self.options['tts_voice'])
                    self.process.stdin.write((json.dumps(data,ensure_ascii=False)+'\n').encode());self.process.stdin.flush()
                    while True:
                        # Drain an expired request to its actual DONE boundary.
                        # Killing a warm model here can prevent continuous TTS
                        # from ever recovering when a sentence misses its slot.
                        event=self._next(deadline,cancelled)
                        if event.get('id')!=identity:raise ValueError('TTS response identity mismatch')
                        if event['event']=='speech_done':break
                        if event['event']!='speech_audio':raise ValueError('unexpected TTS event')
                        sample_rate=event.get('rate');encoded=event.get('pcm','')
                        if type(sample_rate) is not int or not 8000<=sample_rate<=48000 or len(encoded)>131072:
                            raise ValueError('invalid TTS PCM')
                        pcm=base64.b64decode(encoded,validate=True)
                        if len(pcm)%2 or rate not in (None,sample_rate):raise ValueError('invalid TTS sample boundary')
                        if rate is None:rate=sample_rate;output.setframerate(rate)
                        count+=len(pcm)
                        if count>2_000_000:raise ValueError('TTS sentence audio exceeds browser limit')
                        expired=expired or stale()
                        if not expired:output.writeframesraw(pcm)
                    if expired or stale():raise CueExpired('sentence expired during synthesis')
            if not rate or not count:raise ValueError('empty TTS result')
            if stale():raise CueExpired('sentence expired after synthesis')
            temporary.replace(path);return count/2/rate
        finally:temporary.unlink(missing_ok=True)

    def close(self):
        self.closed.set()
        self.job.close()
        if self.process:
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=5)
            for stream in (self.process.stdin,self.process.stdout,self.process.stderr):
                if stream:
                    try:stream.close()
                    except OSError:pass
        for thread in self.threads:thread.join(timeout=1)


class SpeechQueue:
    def __init__(self,options,directory,generation,send,playhead=None,enabled=lambda:True):
        self.options=options;self.directory=Path(directory);self.generation=generation;self.send=send;self.playhead=playhead
        self.queue=queue.Queue(maxsize=8);self.stop=threading.Event();self.client=None
        self.failures=0;self.disabled=False
        self.state={};self.enabled=enabled;self.generated=0;self.skipped=0
        self.revision=options.get('speech_revision',0);self.offered=set();self.offer_lock=threading.Lock()
        self.thread=threading.Thread(target=self._run,daemon=True,name='ELT-Web-TTS');self.thread.start()

    def stale(self,generation,cue):
        return self.stop.is_set() or not self.enabled() or generation!=self.generation.value or (self.playhead is not None and self.playhead.value>=cue.end)

    def offer(self,generation,cue):
        if self.disabled:
            self.send('speech_cue',generation=generation,speech_revision=self.revision,cue=asdict(replace(cue,speech_error=_tr('本地 TTS 连续失败，请停止后重新开始；字幕继续'))));return
        key=(generation,cue.id)
        with self.offer_lock:
            if key in self.offered:return
            self.offered.add(key)
        try:self.queue.put_nowait((generation,cue))
        except queue.Full:
            with self.offer_lock:self.offered.discard(key)
            self.send('speech_cue',generation=generation,speech_revision=self.revision,cue=asdict(replace(cue,speech_error=_tr('TTS 队列已满，保留字幕并跳过本句朗读'))))

    def status(self,**data):
        self.state.update(data,speech_revision=self.revision,generated=self.generated,skipped=self.skipped,queue_depth=self.queue.qsize());self.send('tts_status',**self.state)

    def load(self):
        self.client=QwenFiles(self.options,self.status)
        # A whole model belongs to the session, not to the first short cue.
        self.client.wait_ready(self.stop.is_set)

    def failed(self,error=None):
        self.failures+=1;self.disabled=self.failures>=3
        if self.client:self.client.close();self.client=None
        self.status(status='error',engine='qwen',failures=self.failures,disabled=self.disabled,
                    error_code=getattr(error,'code',type(error).__name__),error_stage=getattr(error,'stage','synthesis'))

    def _run(self):
        try:
            try:self.load()
            except InterruptedError:
                if self.stop.is_set():return
                self.failed()
            except Exception as error:self.failed(error)
            while not self.stop.is_set():
                try:generation,cue=self.queue.get(timeout=.1)
                except queue.Empty:continue
                try:
                    if self.stale(generation,cue):
                        self.skipped+=1;self.status(status='skipped',last_skipped_cue=cue.id);continue
                    if self.disabled:continue
                    if self.client is None:
                        self.load()
                    if self.stale(generation,cue):
                        self.skipped+=1;self.status(status='skipped',last_skipped_cue=cue.id);continue
                    started=time.monotonic();name=f'{self.revision}-{cue.id}.wav'
                    duration=self.client.synthesize(cue.translation,self.directory/name,lambda:self.stale(generation,cue),self.stop.is_set)
                    if self.stale(generation,cue):raise CueExpired('speech disabled or expired')
                    self.send('speech_cue',generation=generation,speech_revision=self.revision,cue=asdict(replace(cue,speech=name,speech_seconds=duration)),
                              tts_seconds=time.monotonic()-started)
                    self.failures=0;self.generated+=1
                    self.status(status='ready',engine='qwen')
                except CueExpired:
                    self.skipped+=1
                    if not self.stop.is_set():self.status(status='skipped',engine='qwen',last_skipped_cue=cue.id)
                except InterruptedError:
                    if self.client:self.client.close();self.client=None
                    if not self.stop.is_set():self.status(status='skipped',engine='qwen')
                except Exception as error:
                    self.failed(error)
                    self.send('speech_cue',generation=generation,speech_revision=self.revision,cue=asdict(replace(cue,speech_error=_tr('本地 TTS 未完成（')+type(error).__name__+_tr('），字幕继续'))))
                finally:
                    with self.offer_lock:self.offered.discard((generation,cue.id))
                    self.queue.task_done()
        finally:
            if self.client:self.client.close();self.client=None

    def close(self):
        self.stop.set();self.thread.join(timeout=8)
        if self.thread.is_alive():raise RuntimeError('TTS worker did not stop')
