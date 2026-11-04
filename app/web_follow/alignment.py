"""Bounded, local waveform check of the course audio against the player clock.

Only the native course process belonging to this GUI can be sampled. No audio
is saved; silence, ambiguity, seeking and unsupported rates are inconclusive.
"""
from collections import deque
from pathlib import Path
import threading
import time

import numpy as np
from scipy.signal import correlate,resample_poly

RATE=16000


def match_audio(reference,captured,reference_start,predicted_start):
    """Two independent 3 s matches must agree within 120 ms before reporting."""
    reference=np.asarray(reference,dtype=np.float32);captured=np.asarray(captured,dtype=np.float32)
    if reference.ndim!=1 or captured.ndim!=1 or len(captured)<8*RATE or len(reference)<len(captured):
        raise ValueError('insufficient alignment audio')
    if not np.isfinite(reference).all() or not np.isfinite(captured).all():raise ValueError('invalid alignment audio')
    # Lower the work size without turning speech into a low-resolution envelope.
    ref=resample_poly(reference,1,4).astype(np.float64);cap=resample_poly(captured,1,4).astype(np.float64)
    sr=RATE//4;matches=[]
    for begin in (.5,4.5):
        sample=cap[round(begin*sr):round((begin+3)*sr)];sample=sample-sample.mean()
        power=float(sample@sample)
        if power/len(sample)<1e-7:raise ValueError('alignment audio is silent')
        sums=np.concatenate(([0.],np.cumsum(ref)));squares=np.concatenate(([0.],np.cumsum(ref*ref)))
        n=len(sample);energy=squares[n:]-squares[:-n]-(sums[n:]-sums[:-n])**2/n
        score=correlate(ref,sample,mode='valid',method='fft')/np.sqrt(np.maximum(energy*power,1e-20))
        index=int(np.argmax(score));peak=float(score[index])
        other=score.copy();other[max(0,index-round(.3*sr)):index+round(.3*sr)+1]=-1
        margin=peak-float(other.max())
        delta=reference_start+index/sr-(predicted_start+begin)
        if peak<.55 or margin<.12 or abs(delta)>4 or index<.15*sr or index>len(score)-.15*sr:
            raise ValueError('audio alignment is ambiguous')
        matches.append((delta,peak,margin))
    if abs(matches[0][0]-matches[1][0])>.12:raise ValueError('audio alignment is not stable')
    return dict(status='measured',offset_seconds=float(np.mean([m[0] for m in matches])),
                correlation=min(m[1] for m in matches),peak_margin=min(m[2] for m in matches),confirmations=2)


def own_player():
    """Resolve one native player in our owning GUI, never another running app."""
    import psutil
    from app.audio.processes import ProcessSelector
    try:
        gui=next((p for p in psutil.Process().parents() if 'app.ui.main' in p.cmdline()),None)
        if gui is None:return None
        rows=[p for p in gui.children(recursive=True) if 'app.web_follow.player' in p.cmdline()]
        ids={p.pid for p in rows};roots=[p for p in rows if p.ppid() not in ids]
        if len(roots)!=1:return None
        from app.audio.source_volume import process_tree
        selector=ProcessSelector();root=selector.inspect(roots[0].pid)
        members=process_tree(root,selector)
        # WebView2 delegates playback to its audio-service process. Target the
        # verified live session itself: the Python launcher can yield silence.
        sources,_=selector.discover('sessions')
        active=[p for p in sources if p.pid in members and p.audio_state=='active']
        return active[0] if len(active)==1 else None
    except (psutil.Error,OSError):return None


class AudioAlignment:
    def __init__(self,source,target,helper):
        self.source=source;self.target=target;self.helper=Path(helper);self.clocks=deque(maxlen=160)
        self.lock=threading.Lock();self.stop=threading.Event();self.session=None
        self.result={'status':'sampling'};self.thread=threading.Thread(target=self._run,daemon=True,name='ELT-Audio-Timing')
        self.thread.start()

    def observe(self,position,paused,rate,seek=False):
        with self.lock:self.clocks.append((time.perf_counter(),position,paused,rate,seek))

    def snapshot(self):
        with self.lock:return dict(self.result)

    def _run(self):
        for attempt in range(1,4):
            if self.stop.is_set():break
            with self.lock:self.result={'status':'sampling','attempt':attempt}
            self._attempt()
            with self.lock:
                self.result['attempt']=attempt;done=self.result.get('status')=='measured'
            if done or self.stop.wait(1):break

    def _attempt(self):
        from app.audio.capture import CaptureSession
        from app.audio.processing import AudioProcessor
        from app.audio.protocol import Kind
        from .media import decode_window
        outcome={};diagnostic={};parts=[];first=None;processor=AudioProcessor();started=time.monotonic()
        try:
            with CaptureSession(self.helper,self.target) as capture:
                self.session=capture
                while not self.stop.is_set() and time.monotonic()-started<15:
                    packet=capture.receive()
                    if packet.kind==Kind.ERROR:raise ValueError('capture could not verify audio timing')
                    if packet.kind!=Kind.AUDIO:continue
                    if first is None:first=packet.timestamp/10_000_000
                    parts.extend(f.samples for f in processor.process(packet))
                    if processor.output_samples>=8*RATE:break
            self.session=None
            if self.stop.is_set():return
            if first is None or processor.output_samples<8*RATE:raise ValueError('insufficient live audio')
            with self.lock:clocks=list(self.clocks)
            nearest=min(clocks,key=lambda c:abs(c[0]-first)) if clocks else None
            if nearest is None or abs(nearest[0]-first)>1:raise ValueError('player clock unavailable')
            relevant=[c for c in clocks if first-.5<=c[0]<=first+8.5]
            step_errors=[abs((b[1]-a[1])-(b[0]-a[0])) for a,b in zip(relevant,relevant[1:])]
            diagnostic=dict(clock_observations=len(relevant),clock_max_step_error_seconds=max(step_errors,default=0),
                            clock_anchor_age_seconds=abs(nearest[0]-first))
            if any(c[2] or abs(c[3]-1)>.001 or c[4] for c in relevant):raise ValueError('player was paused, seeking or not at 1x')
            if any(error>.4 for error in step_errors):
                raise ValueError('player clock changed during measurement')
            predicted=nearest[1]+first-nearest[0];begin=max(0,predicted-4.5);end=begin+18
            reference,_=decode_window(self.source,begin,end,self.stop.is_set)
            if self.stop.is_set():return
            outcome=match_audio(reference,np.concatenate(parts)[:8*RATE],begin,predicted)
            outcome.update(diagnostic,captured_seconds=8)
        except Exception as error:
            outcome={**diagnostic,'status':'inconclusive','reason':str(error) if type(error) is ValueError else type(error).__name__}
        finally:
            self.session=None
            with self.lock:self.result=outcome or {'status':'cancelled'}

    def close(self):
        self.stop.set()
        session=self.session
        if session:
            try:session.stop()
            except (OSError,ValueError):pass
        self.thread.join(timeout=3)
