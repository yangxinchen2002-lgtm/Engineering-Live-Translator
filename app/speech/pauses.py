"""Bounded streaming compaction of long, near-silent pauses, without pitch editing."""
import numpy as np


class PauseCompactor:
    """Keep <=400 ms pauses intact; cap longer near-silence at 320 ms.

    Frames must stay below -60 dBFS RMS throughout the run. Ordinary quiet
    speech and breath pauses are therefore not indiscriminately removed.
    At most 80 ms plus a partial 20 ms frame is held across calls.
    """
    def __init__(self,rate):
        if type(rate) is not int or not 8000<=rate<=48000:raise ValueError('invalid sample rate')
        self.width=round(rate*.02)*2;self.partial=bytearray();self.held=bytearray()
        self.quiet_frames=0;self.flushed=False;self.removed_samples=0

    @staticmethod
    def _quiet(pcm):
        values=np.frombuffer(pcm,dtype='<i2').astype(np.float64)
        return bool(len(values) and np.mean(values*values)<(32768*.001)**2)

    def _frame(self,pcm):
        if self._quiet(pcm):
            self.quiet_frames+=1
            if self.quiet_frames<=16:return pcm
            if self.quiet_frames<=20:self.held.extend(pcm);return b''
            self.removed_samples+=(len(self.held)+len(pcm))//2;self.held.clear();return b''
        result=bytes(self.held)+pcm;self.held.clear();self.quiet_frames=0
        return result

    def convert(self,pcm):
        if self.flushed:raise ValueError('pause compactor already flushed')
        if len(pcm)%2:raise ValueError('invalid PCM length')
        self.partial.extend(pcm);parts=[]
        full=len(self.partial)//self.width*self.width
        for offset in range(0,full,self.width):parts.append(self._frame(bytes(self.partial[offset:offset+self.width])))
        del self.partial[:full]
        return b''.join(parts)

    def flush(self):
        if self.flushed:raise ValueError('pause compactor already flushed')
        self.flushed=True;tail=bytes(self.partial);self.partial.clear()
        if self.quiet_frames>20 and self._quiet(tail):
            self.removed_samples+=len(tail)//2;tail=b''
        result=bytes(self.held)+tail;self.held.clear()
        return result
