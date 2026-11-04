from __future__ import annotations
from collections import deque
import numpy as np
from .types import InputFrame, RATE


class AudioRing:
    """Contiguous sample coordinates, bounded PCM plus per-frame clock mapping."""
    def __init__(self, seconds: float):
        self.capacity = int(seconds * RATE)
        self.data = np.empty(0, np.float32)
        self.start = 0
        self.clocks: deque[tuple[int, int, int]] = deque()

    @property
    def end(self) -> int:
        return self.start + len(self.data)

    def append(self, frame: InputFrame) -> None:
        if frame.start != self.end:
            raise ValueError("audio sample gap/overlap; cannot claim complete transcription")
        if frame.audio.ndim != 1 or frame.audio.dtype != np.float32 or not np.isfinite(frame.audio).all():
            raise ValueError("expected finite Float32 mono audio")
        if len(self.data) + len(frame.audio) > self.capacity:
            raise BufferError("unconsumed audio ring overflow; transcription incomplete")
        self.data = np.concatenate((self.data, frame.audio))
        self.clocks.append((frame.start, frame.end, frame.end_ns))

    def discard_before(self, sample: int) -> None:
        sample = min(max(sample, self.start), self.end)
        self.data = self.data[sample - self.start:].copy()
        self.start = sample
        while self.clocks and self.clocks[0][1] < sample:
            self.clocks.popleft()

    def slice(self, start: int, end: int) -> np.ndarray:
        if not self.start <= start <= end <= self.end:
            raise BufferError("requested audio no longer available")
        return self.data[start - self.start:end - self.start].copy()

    def time_at(self, sample: int) -> int:
        for start, end, timestamp in self.clocks:
            if start <= sample <= end:
                return timestamp - (end - sample) * 1_000_000_000 // RATE
        raise ValueError("no sample-to-monotonic clock mapping")
