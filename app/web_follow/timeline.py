"""Pure, bounded media-clock state; no wall-clock subtitle scheduling."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math


def finite(value, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('expected a number')
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError('number outside allowed range')
    return value


@dataclass(frozen=True)
class Cue:
    id: str
    start: float
    end: float
    source: str
    translation: str = ''
    translation_error: str = ''
    speech: str = ''
    speech_seconds: float = 0
    speech_error: str = ''
    boundary: str = ''
    complete_sentence: bool = True
    source_language: str = ''
    asr_confirmed: bool = False

    def __post_init__(self):
        finite(self.start, 0, 86400)
        finite(self.end, self.start + .001, 86400)
        if not self.source.strip() or len(self.source) > 800:
            raise ValueError('invalid cue text')


class Timeline:
    CAPACITY = 96

    def __init__(self, lookahead=15.):
        self.lookahead = finite(lookahead, 5, 30)
        self.generation = 1
        self.position = self.prepared_until = 0.
        self.paused = True
        self.rate = 1.
        self.cues: list[Cue] = []
        self.duration: float | None = None

    def seek(self, position: float):
        self.position = finite(position, 0, 86399)
        self.generation += 1
        self.prepared_until = self.position
        self.cues.clear()

    def plan(self) -> tuple[float, float] | None:
        target = self.position + self.lookahead
        if self.duration is not None:
            target = min(target, self.duration)
        if self.prepared_until >= target - .05:
            return None
        if (self.prepared_until > self.position and target != self.duration
                and target - self.prepared_until < min(5., self.lookahead / 3)):
            return None  # Refill in useful windows, never transcribe every 400 ms heartbeat.
        # Initial horizon is prepared at once; replenishment is capped at six seconds.
        length = self.lookahead if self.prepared_until == self.position else 6.
        return self.prepared_until, min(target, self.prepared_until + length)

    def commit(self, generation: int, begin: float, end: float, cues: list[Cue]):
        if generation != self.generation:
            return False
        if abs(begin - self.prepared_until) > .025 or end <= begin:
            raise ValueError('non-contiguous preparation result')
        if any(c.start < begin - .025 or c.end > end + .025 for c in cues):
            raise ValueError('cue outside prepared window')
        if any(a.start > b.start for a, b in zip(cues, cues[1:])):
            raise ValueError('out-of-order cues')
        retained = [c for c in self.cues if c.end >= self.position - 30]
        if len(retained) + len(cues) > self.CAPACITY:
            raise ValueError('cue capacity exceeded; playback must stop')
        self.cues = retained + cues
        self.prepared_until = end
        return True

    def snapshot(self):
        return dict(generation=self.generation, position=self.position, paused=self.paused,
                    playback_rate=self.rate, prepared_until=self.prepared_until,
                    ahead_seconds=max(0, self.prepared_until - self.position), duration=self.duration,
                    cues=[asdict(c) for c in self.cues])


def active_cue(cues: list[Cue], position: float) -> Cue | None:
    return next((c for c in reversed(cues) if c.start <= position < c.end), None)


