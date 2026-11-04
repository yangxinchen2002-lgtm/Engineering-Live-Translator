"""Qt playback and bounded, ordered final-subtitle delivery to an isolated TTS worker."""
from app.i18n import tr as _tr
import base64
from collections import OrderedDict,deque
import json
import sys
from pathlib import Path
from .captions import translation_failed
from PySide6.QtCore import QObject,Signal,QProcess,QProcessEnvironment,QTimer
from PySide6.QtMultimedia import QAudioFormat,QAudioSink,QMediaDevices,QAudio
from app.speech.config import ROOT,PYTHON,SpeechConfig,split_for_speech,LECTURE_VOICE,PREVIEW_TEXT,PREVIEW_TEXT_EN
from app.speech.buffering import required_audio_reserve
from app.speech.pacing import CatchUpPacer
from .lifetime import OwnerJob,JOB_ENV
from app.asr.clock import now_ns

LOOKAHEAD_UTTERANCES=3


class SpeechController(QObject):
    status_changed=Signal(str)
    problem=Signal(str)
    diagnostic=Signal(dict)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.config=SpeechConfig();self.process=None;self.job=None;self.generation=0
        self.ready=False;self.active=False;self.paused=False;self.finishing=False;self.user_paused=False
        self.sources=OrderedDict();self.seen=OrderedDict();self.queue=deque();self.session=None
        self.current=None;self.serial=0;self.buffer=b'';self.stderr='';self.pcm=deque();self.pcm_bytes=0
        self.prefetched=deque();self.generating_id=None;self.last_status_ns=0;self.playback_speed=self.config.speed
        self.sink=None;self.audio=None;self.audio_done=False;self.samples=0;self.rate=24000
        self.rendered_samples=0;self.output_rate=24000;self.frame_bytes=2
        self.converter=None
        self.refill_started_ns=None
        self.generation_history=deque(maxlen=4)
        self.pacer=CatchUpPacer();self.catch_up_started=False
        self.timer=QTimer(self);self.timer.setInterval(20);self.timer.timeout.connect(self._tick);self.timer.start()

    def configure(self,config):
        config.validate()
        identity=lambda c:(c.device,c.model_size,c.engine,c.system_voice if c.engine=='system' else None,c.language)
        changed=identity(config)!=identity(self.config)
        if (config.catch_up_start_chars,config.catch_up_grace_seconds)!=(self.config.catch_up_start_chars,self.config.catch_up_grace_seconds):
            self.pacer=CatchUpPacer(config.catch_up_start_chars,config.catch_up_grace_seconds)
        was_enabled=self.config.enabled;self.config=config
        if self.sink:self.sink.setVolume(config.volume/100)
        if changed and (self.process or self.active):
            self.clear(_tr('模型或设备已切换，正在重新准备朗读…'))
        elif was_enabled and not config.enabled:self.stop()
        elif config.enabled and self.active and not self.process:self._load()
        self._status()

    def start(self,session=None):
        if (self.ready and self.process and not self.active and not self.paused and self.current is None
                and not self.prefetched and self.generating_id is None):
            self.sources.clear();self.seen.clear();self.queue.clear();self.finishing=False
            self.active=True;self.session=session;self.status_changed.emit(_tr('朗读已就绪，等待完整译文。'));return
        self.stop();self.active=True;self.paused=False;self.session=session
        if self.config.enabled:self._load()

    def _load(self):
        if self.process:return
        if self.config.engine=='system' and self.config.system_voice<0:
            self.status_changed.emit(_tr('等待可用的 对应语言的 Windows 音色；请检查系统语音包。'));return
        if self.config.engine=='qwen' and (not PYTHON.is_file() or not (self.config.model_path/'model.safetensors').is_file()):
            self._fail(self.config.model_size+_tr(' 本地朗读模型或独立运行环境尚未准备好。'));return
        self.generation+=1;generation=self.generation
        process=QProcess(self);self.process=process;self.ready=False;self.buffer=b'';self.stderr=''
        try:self.job=OwnerJob()
        except OSError:self._fail(_tr('无法建立朗读进程，请重新启动 ELT。'));return
        env=QProcessEnvironment.systemEnvironment();env.insert(JOB_ENV,self.job.name);env.insert('PYTHONUTF8','1')
        env.insert('HF_HUB_OFFLINE','1');env.insert('TRANSFORMERS_OFFLINE','1')
        process.setProcessEnvironment(env);process.setWorkingDirectory(str(ROOT))
        program=Path(sys.executable).with_name('python.exe') if sys.platform=='win32' else Path(sys.executable)
        process.setProgram(str(program if self.config.engine=='system' else PYTHON))
        process.setArguments(['-u','-m','app.speech.worker','--device',self.config.device,'--model-size',self.config.model_size,
                             '--engine',self.config.engine,'--system-voice',str(self.config.system_voice),'--language',self.config.language])
        process.readyReadStandardOutput.connect(lambda:self._read(process,generation))
        process.readyReadStandardError.connect(lambda:self._read_error(process,generation))
        process.finished.connect(lambda code,status:self._finished(process,generation,code))
        process.errorOccurred.connect(lambda error:self._process_error(process,generation,error))
        self.status_changed.emit(_tr('Windows 系统音色准备中…') if self.config.engine=='system' else self.config.model_size+' '+('GPU' if self.config.device=='cuda' else 'CPU')+_tr(' 朗读模型准备中…'))
        process.start()

    def _read_error(self,process,generation):
        data=bytes(process.readAllStandardError()).decode('utf-8','replace')
        if generation==self.generation:self.stderr=(self.stderr+data)[-8000:]

    def _read(self,process,generation):
        data=bytes(process.readAllStandardOutput())
        if generation!=self.generation:return
        self.buffer+=data
        try:
            while b'\n' in self.buffer:
                line,self.buffer=self.buffer.split(b'\n',1)
                if len(line)>262144:raise ValueError('oversized speech message')
                if not line.strip():continue
                self._event(json.loads(line))
                if generation!=self.generation:return
            if len(self.buffer)>262144:raise ValueError('incomplete speech message exceeds limit')
        except (ValueError,KeyError,TypeError):self._fail(_tr('朗读进程返回了无效数据，字幕继续运行。'))

    def _event(self,value):
        event=value['event']
        if event=='speech_ready':
            if self.config.engine=='system' and value.get('engine')!='windows-sapi':raise ValueError('speech engine mismatch')
            if value.get('device')!=self.config.device:raise ValueError('speech device mismatch')
            if value.get('model_size','0.6B')!=self.config.model_size:raise ValueError('speech model mismatch')
            self.ready=True;self.diagnostic.emit(value);self.status_changed.emit(_tr('朗读已就绪，等待完整译文。'));self._next()
        elif event=='speech_error':self._fail(_tr('朗读失败：')+value.get('message',_tr('未知错误')))
        elif event in ('speech_audio','speech_done'):
            utterance=next((u for u in (self.current,*self.prefetched) if u and value.get('id')==u['id']),None)
            if utterance is None or value.get('id')!=self.generating_id:return
            if event=='speech_audio':
                rate=value['rate']
                if type(rate) is not int or not 8000<=rate<=48000 or len(value['pcm'])>131072:raise ValueError('invalid PCM format')
                pcm=base64.b64decode(value['pcm'],validate=True)
                if len(pcm)%2:raise ValueError('invalid PCM sample count')
                if utterance['rate'] not in (None,rate):raise ValueError('speech rate changed mid-utterance')
                buffered=sum(u['raw_bytes'] for u in (self.current,*self.prefetched) if u)+self.pcm_bytes
                if buffered+len(pcm)>32*1024*1024:
                    self._fail(_tr('朗读音频缓冲已满，请清空待播后重试。'));return
                utterance['rate']=rate;utterance['samples']+=len(pcm)//2
                if pcm:
                    arrived=now_ns();previous=utterance.get('last_audio_ns')
                    if previous is not None:
                        utterance['largest_chunk_gap']=max(utterance.get('largest_chunk_gap',0),(arrived-previous)/1e9)
                    utterance['last_audio_ns']=arrived
                    utterance['raw'].append(pcm);utterance['raw_bytes']+=len(pcm)
            else:
                utterance['done']=True;self.generating_id=None
                duration=value.get('audio_seconds',0);elapsed=value.get('generation_seconds',0)
                if duration>0 and elapsed>0 and value.get('first_audio_seconds',0)<2:
                    # Tiny clips mostly measure fixed prefill cost, not steady
                    # decoding throughput. Retain their observed chunk gaps.
                    rate=elapsed/duration if duration>=2 else 0.
                    self.generation_history.append((rate,utterance.get('largest_chunk_gap',0)))
                self.diagnostic.emit({k:v for k,v in value.items() if k!='pcm'})
                self._prefetch()

    def _append_pcm(self,chunks):
        for pcm in chunks:
            if self.pcm_bytes+len(pcm)>32*1024*1024:
                self._fail(_tr('朗读音频缓冲已满，请清空待播后重试。'));return
            if pcm:
                if len(pcm)%self.frame_bytes:raise ValueError('incomplete playback frame')
                self.pcm.append(pcm);self.pcm_bytes+=len(pcm);self.rendered_samples+=len(pcm)//self.frame_bytes

    def _open_audio(self,rate):
        output=QMediaDevices.defaultAudioOutput()
        if output.isNull():self._fail(_tr('未找到声音输出设备，请连接耳机或扬声器。'));return
        format=QAudioFormat();format.setSampleRate(rate);format.setChannelCount(1);format.setSampleFormat(QAudioFormat.Int16)
        if not output.isFormatSupported(format):format=output.preferredFormat()
        formats={QAudioFormat.Int16:'s16',QAudioFormat.Int32:'s32',QAudioFormat.Float:'flt',QAudioFormat.UInt8:'u8'}
        try:
            from app.speech.playback import PlaybackConverter
            self.playback_speed=self._desired_speed()
            self.converter=PlaybackConverter(rate,format.sampleRate(),format.channelCount(),formats[format.sampleFormat()],
                                             self.playback_speed,dynamic=True,
                                             compact_pauses=self.config.engine=='qwen' and self.current.get('voice')==LECTURE_VOICE)
        except (ImportError,KeyError,ValueError):self._fail(_tr('当前声音设备格式不可用，请检查播放组件或切换系统输出设备。'));return
        self.output_rate=format.sampleRate();self.frame_bytes=format.bytesPerFrame();self.rendered_samples=0
        self.rate=rate;self.sink=QAudioSink(output,format,self)
        self.sink.setBufferSize(format.sampleRate()*format.bytesPerFrame()//5)
        self.sink.setVolume(self.config.volume/100);self.audio=self.sink.start()
        if self.audio is None:self._fail(_tr('声音输出无法启动。'))
        else:self.diagnostic.emit({'event':'speech_audio_reserve','id':self.current['id'],
                                  'buffered_raw_seconds':self.current['raw_bytes']/2/rate,
                                  'submit_to_open_seconds':(now_ns()-self.current['submitted_ns'])/1e9,
                                  'sink_buffer_seconds':self.sink.bufferSize()/format.sampleRate()/format.bytesPerFrame()})

    def _audio_ready(self):
        if self.current['done']:return True
        rate=self.current['rate'];produced=self.current['samples']/rate
        elapsed=max(0,(self.current.get('last_audio_ns',now_ns())-self.current['submitted_ns'])/1e9)
        recent=max((rtf for rtf,_ in self.generation_history),default=0)
        gap=max(self.current.get('largest_chunk_gap',0),max((gap for _,gap in self.generation_history),default=0))
        reserve=required_audio_reserve(produced,elapsed,len(self.current['text']),self._desired_speed(),
                                       recent_rtf=recent,jitter_seconds=max(.5,gap*1.25))
        return self.current['raw_bytes']/2/rate>=reserve

    def offer(self,record):
        if not self.config.enabled or not self.active or self.paused:return
        if record.get('session_id')!=self.session:
            if self.session is not None:return
            self.session=record.get('session_id')
        key=record['segment_id']
        if key in self.seen:return
        if key not in self.sources and len(self.sources)>=32:
            self._fail(_tr('朗读等待的字幕过多，已暂停朗读。字幕和存稿继续；可清空待播后恢复。'));return
        self.sources[key]=dict(record);self.sources=OrderedDict(sorted(self.sources.items()))
        self._collect()

    def _remember(self,key):
        self.seen[key]=True
        while len(self.seen)>2048:self.seen.popitem(last=False)

    def _collect(self):
        while self.sources:
            key,record=next(iter(self.sources.items()))
            complete=bool(record.get('source_closed') and record.get('state')=='final' and record.get('translated_text','').strip()
                          and record.get('translated_revision')==record.get('revision'))
            failed=bool(record.get('source_closed') and translation_failed(record) and not record.get('translation_retry_pending'))
            if not complete and not failed:break
            if complete:
                if not self._enqueue(record['translated_text']):return
            else:self.diagnostic.emit({'event':'speech_skipped_untranslated','segment_id':key})
            self.sources.pop(key);self._remember(key)
        self._next()

    def _next(self):
        if self.paused or self.user_paused or not self.ready:return
        if self.current is None:
            if self.prefetched:
                self.current=self.prefetched.popleft()
            elif self.queue and self.generating_id is None:self.current=self._submit()
            if self.current:
                self.audio_done=False;self.samples=0;self.rendered_samples=0;self._status()
        self._prefetch()

    def _enqueue(self,text):
        chunks=split_for_speech(text,60 if self.config.engine=='qwen' and self.config.device=='cpu' else 160)
        if len(self.queue)+len(chunks)>32:
            self._fail(_tr('朗读排队已满，已暂停。字幕和存稿继续；可清空待播后恢复。'));return False
        queued=now_ns();self.queue.extend((text,queued) for text in chunks);return True

    def enqueue(self,text):
        if self._enqueue(text):self._next()

    def _submit(self):
        if not self.queue:return None
        text,queued=self.queue.popleft()
        self.serial+=1
        utterance={'id':str(self.serial),'text':text,'voice':self.config.voice,'queued_ns':queued,'submitted_ns':now_ns(),'playing':False,
                   'raw':deque(),'raw_bytes':0,'rate':None,'samples':0,'done':False}
        self.generating_id=utterance['id']
        command={'id':utterance['id'],'text':text,'voice':utterance['voice']}
        self.process.write((json.dumps(command,ensure_ascii=False)+'\n').encode('utf-8'))
        self.diagnostic.emit({'event':'speech_utterance_submitted','id':utterance['id'],'source_parts':1,
                              'characters':sum(c.isalnum() for c in text),'queue_to_submit_seconds':(now_ns()-queued)/1e9})
        return utterance

    def _prefetch(self):
        # Keep a few separate utterances ready across short/long transitions.
        # Decode only one at a time on the existing worker; total PCM remains bounded.
        if (self.ready and not self.paused and not self.user_paused and self.current and self.current['done']
                and len(self.prefetched)<LOOKAHEAD_UTTERANCES and self.generating_id is None and self.queue):
            utterance=self._submit()
            if utterance:
                self.prefetched.append(utterance)
                self.diagnostic.emit({'event':'speech_prefetch_started','id':utterance['id'],'playing_id':self.current['id'],
                                      'lookahead_utterances':len(self.prefetched)})

    def _waiting(self):
        pending=[(u['text'],u['queued_ns']) for u in self.prefetched]+list(self.queue)
        age=max(0,(now_ns()-pending[0][1])/1e9) if pending else 0.
        return pending,age

    def _backlog_characters(self):
        pending,_=self._waiting();texts=[text for text,_ in pending]
        if self.current and not self.current.get('playing'):texts.append(self.current.get('text',''))
        return sum(character.isalnum() for text in texts for character in text)

    def _desired_speed(self):
        # The initial grace starts with actual playback, not GPU model loading.
        if not self.catch_up_started:
            self.pacer.reset();return self.config.speed
        return self.pacer.update(self._backlog_characters(),self.config.speed,self.config.auto_catch_up,now_ns())

    def _status(self):
        if self.user_paused:self.status_changed.emit(_tr('朗读已暂停，待播内容已保留。'));return
        if not self.current:
            if self.queue:
                self.last_status_ns=now_ns();self.status_changed.emit(f"{_tr('等待语音模型就绪 · 待合成 ')}{len(self.queue)}{_tr(' 段 / ')}{self._backlog_characters()}{_tr(' 字')}")
            return
        pending,age=self._waiting();self.last_status_ns=now_ns()
        speed=self.playback_speed if self.sink else self._desired_speed()
        state=_tr('语音正在缓冲') if self.refill_started_ns is not None or self.sink is None else _tr('正在朗读')
        text=f"{state} · {speed:.2f}{_tr(' 倍 · 待播 ')}{len(pending)}{_tr(' 段 / ')}{self._backlog_characters()}{_tr(' 字')}"
        if self.pacer.active:text+=_tr(' · 自动追赶')
        elif self.pacer.above_since is not None:text+=_tr(' · 积压缓冲中')
        if pending:text+=f"{_tr(' · 最久等待 ')}{age:.0f}{_tr(' 秒')}"
        if self.config.engine=='system':text+=_tr(' · Windows 系统音色')
        elif self.config.device=='cpu':text+=_tr(' · CPU 生成较慢')
        self.status_changed.emit(text)

    def _tick(self):
        try:self._play_tick()
        except Exception as error:
            self.diagnostic.emit({'event':'speech_playback_error','error_type':type(error).__name__})
            self._fail(_tr('声音处理失败，请清空待播后重试；字幕和存稿继续。'))

    def _play_tick(self):
        if self.user_paused:return
        # Continue queued speech and bounded look-ahead generation.
        self._next()
        if self.current and self.current['raw'] and self.sink is None and self._audio_ready():
            self._open_audio(self.current['rate'])
        if self.refill_started_ns is not None:
            # If the prediction was insufficient, finish generating this one
            # utterance before resuming instead of repeatedly playing fragments.
            if not self.current['done']:
                if now_ns()-self.last_status_ns>500000000:self._status()
                return
            self.diagnostic.emit({'event':'speech_audio_refilled','id':self.current['id'],
                                  'wait_seconds':(now_ns()-self.refill_started_ns)/1e9})
            self.refill_started_ns=None
        if self.sink and self.audio:
            # An empty push-mode sink enters Idle/Underrun both between streaming
            # chunks and after the final sample. Writing new data resumes it.
            if self.sink.error() not in (QAudio.Error.NoError,QAudio.Error.UnderrunError):
                self._fail(_tr('声音设备播放失败，请检查系统输出设备。'));return
            speed=self._desired_speed()
            if self.converter:
                self.converter.set_speed(speed);self.playback_speed=speed
                # Convert only a small amount ahead, so a speed change takes effect
                # within the next audio chunk instead of behind seconds of queued PCM.
                while self.current['raw'] and self.pcm_bytes<self.output_rate*self.frame_bytes*.3:
                    pcm=self.current['raw'].popleft();self.current['raw_bytes']-=len(pcm)
                    self._append_pcm(self.converter.convert(pcm))
                if self.current['done'] and not self.current['raw'] and not self.audio_done:
                    self._append_pcm(self.converter.convert(b''));self.audio_done=True
            self.samples=self.current['samples']
            while self.pcm and self.sink.bytesFree()>0:
                chunk=self.pcm[0];size=min(len(chunk),self.sink.bytesFree())
                written=self.audio.write(chunk[:size])
                if written<=0:break
                if self.current and not self.current['playing']:
                    self.current['playing']=True;self.current['playback_started_ns']=now_ns()
                    self.catch_up_started=True
                    self.diagnostic.emit({'event':'speech_playback_buffer_started','id':self.current['id'],
                                          'submit_to_buffer_seconds':(now_ns()-self.current['submitted_ns'])/1e9,
                                          'queue_to_buffer_seconds':(now_ns()-self.current['queued_ns'])/1e9,
                                          'speed':self.playback_speed})
                self.pcm_bytes-=written
                if written==len(chunk):self.pcm.popleft()
                else:self.pcm[0]=chunk[written:]
            if (self.current and self.current.get('playing') and not self.current['done']
                    and not self.current['raw'] and not self.pcm and self.sink.state()==QAudio.State.IdleState
                    and self.sink.processedUSecs()+20000>=self.rendered_samples/self.output_rate*1e6):
                self.refill_started_ns=now_ns()
                self.diagnostic.emit({'event':'speech_audio_underrun','id':self.current['id'],
                                      'received_audio_seconds':self.current['samples']/self.current['rate'],
                                      'speed':self.playback_speed})
            if (self.current and self.audio_done and not self.pcm and self.sink.state()==QAudio.State.IdleState
                    and self.sink.processedUSecs()+50000>=self.rendered_samples/self.output_rate*1e6):
                event={'event':'speech_playback_finished','id':self.current['id'],
                       'processed_microseconds':self.sink.processedUSecs(),'speed':self.playback_speed}
                generation=self.generation;self._close_audio();self.current=None;self.diagnostic.emit(event)
                if generation!=self.generation:return
                self._next()
                if not self.current:
                    self.status_changed.emit(_tr('朗读已就绪，等待完整译文。') if self.active else _tr('本次朗读已结束。'))
                    if self.finishing and not self.queue and not self.prefetched:self._shutdown()
        if (self.current or self.queue) and now_ns()-self.last_status_ns>500000000:self._status()

    def pause_playback(self,paused):
        if self.user_paused==paused:return
        self.user_paused=paused;self.pacer.reset()
        self.catch_up_started=bool(not paused and self.current and self.current.get('playing'))
        if self.sink:
            if paused:self.sink.suspend()
            elif not self.paused:self.sink.resume()
        if not paused:self._next()
        self._status()

    def preview(self):
        if self.active:
            self.problem.emit(_tr('请先停止字幕，再试听音色。切换音色会应用到后续朗读。'));return
        if self.current or self.prefetched:self.clear(_tr('正在准备音色试听…'))
        else:self.queue.clear();self.sources.clear()
        self.paused=False;self.finishing=False
        self._enqueue(PREVIEW_TEXT if self.config.language=='zh' else PREVIEW_TEXT_EN)
        self._load();self._next()

    def clear(self,message=None):
        if message is None:message=_tr('已清空待播，继续朗读新译文。')
        active=self.active;session=self.session;known=list(self.sources)
        self._shutdown();self.queue.clear();self.sources.clear();self.current=None;self.paused=False;self.finishing=False
        for key in known:self._remember(key)
        self.active=active;self.session=session
        if active and self.config.enabled:self._load()
        self.status_changed.emit(message)

    def finish_input(self):
        self.active=False;self.finishing=True
        self._next()
        if not self.current and not self.prefetched and not self.queue:self._shutdown();self.status_changed.emit(_tr('本次朗读已结束。'))
        else:self._status()

    def stop(self):
        self.active=False;self.finishing=False;self.paused=False;self.user_paused=False;self.sources.clear();self.seen.clear();self.queue.clear();self.session=None
        self.current=None;self._shutdown();self.status_changed.emit(_tr('朗读未启动'))

    def _close_audio(self):
        if self.sink:self.sink.stop();self.sink.deleteLater()
        self.sink=None;self.audio=None;self.pcm.clear();self.pcm_bytes=0
        self.converter=None
        self.refill_started_ns=None

    def _shutdown(self):
        self.generation+=1;self.ready=False;self._close_audio();self.current=None;self.prefetched.clear();self.generating_id=None
        self.generation_history.clear()
        self.pacer.reset();self.catch_up_started=False
        process,self.process=self.process,None;job,self.job=self.job,None
        if process:
            if process.state()!=QProcess.NotRunning:process.kill();process.finished.connect(process.deleteLater)
            else:process.deleteLater()
        if job:job.close()

    def _fail(self,message):
        self.paused=True;self.queue.clear();self.sources.clear();self._shutdown()
        self.status_changed.emit(message);self.problem.emit(message)

    def _finished(self,process,generation,code):
        if generation!=self.generation:return
        self._read_error(process,generation)
        self._fail(_tr('朗读进程已退出，请清空待播或重新开启朗读。'))

    def _process_error(self,process,generation,error):
        if generation==self.generation and error==QProcess.FailedToStart:self._fail(_tr('朗读进程无法启动，请检查本地运行环境。'))

    def close(self):
        self.timer.stop();self.stop()
