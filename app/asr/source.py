from __future__ import annotations
import queue
import threading
import time
from pathlib import Path
import numpy as np
from app.audio.capture import CaptureSession
from app.audio.processes import ProcessInfo, ProcessSelector
from app.audio.processing import AudioProcessor
from app.audio.protocol import Kind
from .types import InputFrame, RATE
from .clock import now_ns, validate_capture_timestamp


class AudioSource:
    """One owned producer thread, bounded handoff, separate terminal error state."""
    def __init__(self, capacity: int, emit):
        self.queue: queue.Queue[InputFrame] = queue.Queue(maxsize=capacity)
        self.stop_event = threading.Event()
        self.done = threading.Event()
        self.ready = threading.Event()
        self.ready_info: dict = {}
        self.error: BaseException | None = None
        self.thread: threading.Thread | None = None
        self.emit = emit
        self.origin_ns: int | None = None
        self.high_water = 0

    def _offer(self, frame: InputFrame, block: bool = False) -> None:
        while not self.stop_event.is_set():
            try:
                self.queue.put(frame, block=block, timeout=0.1 if block else None)
                self.high_water = max(self.high_water, self.queue.qsize())
                return
            except queue.Full:
                if not block:
                    raise BufferError(f"audio receiver queue overflow at sample {frame.start}; audio incomplete")

    def start(self) -> None:
        def guarded():
            try:
                self._produce()
            except BaseException as exc:
                self.error = exc
            finally:
                self.done.set()
        self.thread = threading.Thread(target=guarded, name="ELT-AudioReceiver", daemon=True)
        self.thread.start()

    def _produce(self) -> None:
        raise NotImplementedError

    def close(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)
            if self.thread.is_alive():
                raise RuntimeError("audio receiver did not stop within its lifecycle deadline")


class LiveSource(AudioSource):
    def __init__(self, helper: Path, target: ProcessInfo, seconds: float, capacity: int, emit, *, pause_event=None):
        super().__init__(capacity, emit)
        self.helper, self.target, self.seconds = helper, target, seconds
        self.pause_event = pause_event if pause_event is not None else threading.Event()
        self.pause_events: queue.Queue[dict] = queue.Queue(maxsize=8)

    def _transition(self,paused,sample):
        # Consumed on the pipeline thread at this exact active-audio boundary.
        try:self.pause_events.put_nowait({'paused':paused,'sample':sample})
        except queue.Full as exc:raise BufferError('capture pause event queue overflow; session incomplete') from exc

    def _produce(self):
        started = time.monotonic(); offset = 0; paused = False
        def ending():return self.stop_event.is_set() or time.monotonic()-started>=self.seconds
        while not ending():
            if self.pause_event.is_set():
                if not paused:self._transition(True,offset);paused=True
                try:current=ProcessSelector().inspect(self.target.pid)
                except OSError as exc:raise RuntimeError('target_exited during pause') from exc
                if current!=self.target:
                    raise RuntimeError('target_exited or target identity changed during pause')
                self.stop_event.wait(.1)
                continue
            offset += self._capture(offset,ending,resuming=paused)
            # A pause ACK is issued only after STOP has drained PCM and reaped
            # the helper. No paused audio is buffered for later replay.
            if self.pause_event.is_set() and not ending():
                self._transition(True,offset);paused=True

    def _capture(self,offset,ending,*,resuming):
        processor = AudioProcessor()
        session = CaptureSession(self.helper, self.target)
        stopped_at = None
        last_packet = None; count = 0
        def offer_frames(frames):
            nonlocal count
            for frame in frames:
                assert last_packet is not None
                delay = processor.resampler.delay_samples if processor.resampler else 0
                end_ns = last_packet.timestamp * 100 + round(
                    ((frame.start_sample + len(frame.samples) - delay) / RATE - last_packet.first_sample / last_packet.rate) * 1e9)
                if self.origin_ns is None:
                    self.origin_ns = end_ns - (frame.start_sample + len(frame.samples)) * 1_000_000_000 // RATE
                self._offer(InputFrame(offset+frame.start_sample, frame.samples, end_ns))
                count = frame.start_sample+len(frame.samples)
        try:
            while True:
                if (ending() or self.pause_event.is_set()) and stopped_at is None:
                    session.stop()
                    stopped_at = time.monotonic()
                if stopped_at and time.monotonic() - stopped_at > 8:
                    raise TimeoutError("native STOP deadline exceeded")
                packet = session.receive()
                if packet.kind == Kind.AUDIO:
                    validate_capture_timestamp(packet.timestamp, now_ns())
                    last_packet = packet
                    offer_frames(processor.process(packet))
                else:
                    info = packet.json()
                    # Do not write console/log I/O from the audio receiver thread.
                    if packet.kind == Kind.ERROR:
                        raise RuntimeError(f"native capture: {info}")
                    if info.get('state')=='started':
                        self.ready_info=info;self.ready.set()
                        if resuming:self._transition(False,offset)
                    if info.get("state") == "stopped":
                        if stopped_at is None:
                            raise RuntimeError("unexpected native stop")
                        offer_frames(processor.finish())
                        break
        finally:
            session.close()
        if session.returncode != 0:
            raise RuntimeError(f"native exit={session.returncode}: {session.stderr}")
        return count


class FileSource(AudioSource):
    def __init__(self, path: Path, seconds: float, realtime: bool, capacity: int, emit):
        super().__init__(capacity, emit)
        if not path.is_file():
            raise FileNotFoundError(path)
        self.path, self.seconds, self.realtime = path, seconds, realtime

    def _produce(self):
        import av
        self.origin_ns = now_ns()
        pending = np.empty(0, np.float32)
        position = 0
        limit = int(self.seconds * RATE)
        def distribute(audio, final=False):
            nonlocal pending, position
            pending = np.concatenate((pending, audio))
            while len(pending) >= 320 or (final and len(pending)):
                if position >= limit or self.stop_event.is_set():
                    return
                size = min(320, len(pending), limit - position)
                chunk = pending[:size].copy()
                pending = pending[size:]
                end_ns = self.origin_ns + (position + size) * 1_000_000_000 // RATE
                if self.realtime:
                    delay = (end_ns - now_ns()) / 1e9
                    if delay > 0 and self.stop_event.wait(delay):
                        return
                self._offer(InputFrame(position, chunk, end_ns), block=not self.realtime)
                position += size
        with av.open(str(self.path)) as container:
            if not container.streams.audio:
                raise ValueError("media file contains no audio stream")
            self.ready_info={'kind':'file','signal':'unverified'};self.ready.set()
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=RATE)
            for frame in container.decode(container.streams.audio[0]):
                for converted in resampler.resample(frame):
                    distribute(converted.to_ndarray().reshape(-1).astype(np.float32))
                if position >= limit or self.stop_event.is_set():
                    break
            if position < limit and not self.stop_event.is_set():
                for converted in resampler.resample(None):
                    distribute(converted.to_ndarray().reshape(-1).astype(np.float32))
                distribute(np.empty(0, np.float32), final=True)
