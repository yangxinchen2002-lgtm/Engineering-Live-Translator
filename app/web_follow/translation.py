"""Bounded sentence translation, independent of the source pre-reading clock."""
from __future__ import annotations
from app.i18n import tr as _tr
import asyncio
from collections import deque
from dataclasses import asdict,replace
from pathlib import Path
import queue
import threading
import time

from app.translation.usage import UsageLedger
from .worker import translate_cues
from .speech import synthesize
from .timeline import Cue


class CueTranslator:
    def __init__(self,options,generation,send,directory,speech=None,playhead=None,narration=None,reading_commands=None,own_speech=False):
        self.options=options;self.generation=generation;self.send=send;self.directory=Path(directory)
        self.speech=speech;self.playhead=playhead;self.queue=queue.Queue(maxsize=8);self.stop=threading.Event()
        self.narration=narration;self.owns_speech=own_speech;self.reading_commands=reading_commands
        self.ledger=UsageLedger(options['model'],provider=options['provider'])
        self.lock=threading.Lock();self.usage=self.ledger.snapshot();self.busy=False;self.dropped=0;self.expired=0
        self.last_seconds=None;self.thread=threading.Thread(target=self._run,daemon=True,name='ELT-Web-Translation');self.thread.start()

    def snapshot(self):
        with self.lock:return self.usage

    def stale(self,generation):return self.stop.is_set() or generation!=self.generation.value

    def narrating(self):return bool(self.narration.value) if self.narration is not None else self.options['narrate']

    def speech_for(self,generation,value):
        if not value.translation or not self.narrating():return
        if self.speech is None and self.options.get('speech_engine')=='qwen':
            from .tts import SpeechQueue
            self.speech=SpeechQueue(dict(self.options),self.directory,self.generation,self.send,self.playhead,self.narrating)
            self.owns_speech=True
        if self.speech:self.speech.offer(generation,value)
        elif not self._expired(value):
            try:
                revision=self.options.get('speech_revision',0);name=f'{revision}-{value.id}.wav'
                duration=(synthesize(value.translation,self.directory/name,self.options['voice']) if self.options.get('target_language','zh')=='zh' else
                          synthesize(value.translation,self.directory/name,self.options['voice'],language=self.options['target_language']))
                if not self.stale(generation) and self.narrating():
                    self.send('speech_cue',generation=generation,speech_revision=revision,
                              cue=asdict(replace(value,speech=name,speech_seconds=duration)))
            except Exception as error:
                if not self.stale(generation):self.send('speech_cue',generation=generation,speech_revision=self.options.get('speech_revision',0),
                    cue=asdict(replace(value,speech_error=_tr('朗读准备失败：')+type(error).__name__)))

    def apply_reading_commands(self):
        if self.reading_commands is None:return
        try:command=self.reading_commands.get_nowait()
        except queue.Empty:return
        options=command['options']
        changed=options.get('speech_revision',0)!=self.options.get('speech_revision',0)
        if changed and self.speech:
            self.speech.close();self.speech=None;self.owns_speech=False
        self.options.update(options)
        if self.narrating():
            for value in command['cues']:
                cue=Cue(**value)
                if not self.stale(command['generation']):self.speech_for(command['generation'],cue)

    def _expired(self,cue):return self.playhead is not None and self.playhead.value>cue.end+5

    def _account(self):
        value=self.ledger.snapshot()
        with self.lock:self.usage=value
        return value

    def status(self):
        with self.queue.mutex:
            depth=len(self.queue.queue);oldest=time.monotonic()-self.queue.queue[0][3] if depth else 0
        self.send('translation_status',translation_queue=depth,translation_busy=self.busy,
            translation_oldest_seconds=oldest,translation_overflow=self.dropped,translation_expired=self.expired,
            translation_last_seconds=self.last_seconds,usage=self.snapshot())

    def _failure(self,generation,cue,message):
        if not self.stale(generation):
            self.send('cue',generation=generation,cue=asdict(replace(cue,translation_error=message)),usage=self.snapshot())

    def offer(self,generation,cue,language):
        try:self.queue.put_nowait((generation,cue,language,time.monotonic()))
        except queue.Full:
            self.dropped+=1;self._failure(generation,cue,_tr('翻译队列已满，本句中文未处理；原文已保留'))
        self.status()

    def _run(self):
        context=deque(maxlen=5);previous=None
        try:
            while not self.stop.is_set():
                try:self.apply_reading_commands()
                except Exception as error:self.send('tts_status',status='error',engine=self.options.get('speech_engine'),
                    speech_revision=self.options.get('speech_revision',0),error_code=type(error).__name__)
                try:generation,cue,language,queued=self.queue.get(timeout=.1)
                except queue.Empty:continue
                try:
                    if self.stale(generation):continue
                    if self._expired(cue):
                        self.expired+=1;self._failure(generation,cue,_tr('翻译任务已过时，本句中文未处理；原文已保留'));continue
                    if generation!=previous:context.clear();previous=generation
                    self.busy=True;self.status();started=time.monotonic()
                    def published(value):
                        # Source and Chinese are visible before speech synthesis.
                        self.last_seconds=time.monotonic()-started
                        self.send('cue',generation=generation,cue=asdict(value),usage=self._account())
                        self.speech_for(generation,value)
                        return value
                    asyncio.run(translate_cues([cue],language,self.options,context,self.ledger,
                                              lambda:self.stale(generation),published))
                except InterruptedError:pass
                except Exception as error:self._failure(generation,cue,_tr('翻译暂不可用（')+type(error).__name__+_tr('），原文已保留'))
                finally:
                    self._account();self.busy=False;self.queue.task_done();self.status()
        finally:
            self._account();self.status()

    def close(self):
        self.stop.set();self.thread.join(timeout=4)
        if self.thread.is_alive():raise RuntimeError('translation thread did not stop')
        if self.owns_speech and self.speech:self.speech.close()
