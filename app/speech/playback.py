"""Stateful PCM conversion to the selected Windows device's actual mix format."""
import av
import numpy as np
from fractions import Fraction
import math


class PlaybackConverter:
    def __init__(self,source_rate,target_rate,channels,sample_format,speed=1.,*,dynamic=False,compact_pauses=False):
        layouts={1:'mono',2:'stereo',4:'quad',6:'5.1',8:'7.1'}
        if channels not in layouts or sample_format not in ('s16','s32','flt','u8'):
            raise ValueError('unsupported playback format')
        self.source_rate=source_rate
        from .pauses import PauseCompactor
        self.pause_compactor=PauseCompactor(source_rate) if compact_pauses else None
        self.resampler=av.AudioResampler(format=sample_format,layout=layouts[channels],rate=target_rate)
        self.graph=None;self.tempo=None;self.tempo_tail=None;self.pts=0;self.flushed=False;self.speed=1.
        if dynamic or speed!=1:
            self.graph=av.filter.Graph()
            self.input=self.graph.add('abuffer',f'sample_rate={source_rate}:sample_fmt=s16:channel_layout=mono:time_base=1/{source_rate}')
            self.tempo=self.graph.add('atempo',str(min(speed,2.)))
            self.tempo_tail=self.graph.add('atempo',str(max(1.,speed/2.)))
            self.output=self.graph.add('abuffersink')
            self.graph.link_nodes(self.input,self.tempo,self.tempo_tail,self.output);self.graph.configure()
        self.set_speed(speed)

    def set_speed(self,speed):
        if type(speed) not in (int,float) or not math.isfinite(speed) or not .8<=speed<=3:
            raise ValueError('unsupported playback speed')
        if speed!=self.speed:
            if self.tempo is None:raise ValueError('tempo conversion is not enabled')
            self.tempo.process_command('tempo',str(min(speed,2.)))
            self.tempo_tail.process_command('tempo',str(max(1.,speed/2.)));self.speed=speed

    def convert(self,pcm):
        if self.flushed:raise ValueError('audio converter already flushed')
        if len(pcm)%2:raise ValueError('invalid PCM length')
        if self.pause_compactor:
            final=not pcm
            filtered=self.pause_compactor.flush() if final else self.pause_compactor.convert(pcm)
            result=self._convert(filtered) if filtered else []
            if final:result.extend(self._convert(b''))
            return result
        return self._convert(pcm)

    def _convert(self,pcm):
        if pcm:
            frame=av.AudioFrame.from_ndarray(np.frombuffer(pcm,dtype='<i2').reshape(1,-1),format='s16',layout='mono')
            frame.sample_rate=self.source_rate
            frame.time_base=Fraction(1,self.source_rate);frame.pts=self.pts;self.pts+=frame.samples
        else:frame=None
        result=[]
        if self.graph:
            self.input.push(frame)
            while True:
                try:converted=self.output.pull()
                except (av.error.BlockingIOError,av.error.EOFError):break
                result.extend(self.resampler.resample(converted))
            if frame is None:result.extend(self.resampler.resample(None))
        else:result.extend(self.resampler.resample(frame))
        if frame is None:self.flushed=True
        return [frame.to_ndarray().tobytes() for frame in result]
