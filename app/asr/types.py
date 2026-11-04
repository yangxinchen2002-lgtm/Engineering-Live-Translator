from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

RATE = 16000


@dataclass(frozen=True)
class Word:
    text: str
    start: int
    end: int


@dataclass
class ASRJob:
    id: int
    segment_id: int
    start: int
    end: int
    audio: np.ndarray
    required: bool
    endpoint: bool
    audio_end_ns: int
    created_ns: int
    language: str | None = None
    submitted_ns: int = 0
    clock_spans: list[tuple[int, int, int]] = field(default_factory=list)

    def time_at(self, sample: int) -> int:
        for start, end, timestamp in self.clock_spans:
            if start <= sample <= end:
                return timestamp - (end - sample) * 1_000_000_000 // RATE
        if not self.clock_spans and self.start <= sample <= self.end:
            return self.audio_end_ns - (self.end - sample) * 1_000_000_000 // RATE
        raise ValueError("word is outside job clock mapping")


@dataclass
class ASRResult:
    id: int
    words: list[Word]
    language: str
    language_probability: float
    started_ns: int
    finished_ns: int
    text: str = ""
    repetition_retry: bool = False
    initial_word_count: int = 0
    course_terms_applied: bool = False


@dataclass(frozen=True)
class InputFrame:
    start: int
    audio: np.ndarray
    end_ns: int

    @property
    def end(self) -> int:
        return self.start + len(self.audio)
