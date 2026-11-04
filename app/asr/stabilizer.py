from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
import unicodedata
from .types import Word, RATE
from app.languages import join_source, NO_SPACE_LANGUAGES


def normalize_word(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum() or c in "'’")


def render_words(words: list[Word], language: str | None = None) -> str:
    return join_source((w.text for w in words), language)


@dataclass(frozen=True)
class TranscriptUpdate:
    revision: int
    committed: list[Word]
    candidate: list[Word]
    reason: str
    expired: list[Word] = field(default_factory=list)


class TranscriptStabilizer:
    """Timestamp-constrained consecutive-hypothesis Local Agreement.

    Normalization is only for comparison; display uses latest spelling/punctuation.
    Endpoint commit is a separate, explicitly labeled segmentation heuristic.
    It is not a promise that words are correct or a translation Final state.
    """
    def __init__(self, tolerance_seconds: float = 0.6, tail_seconds: float = 0.3):
        self.tolerance = int(tolerance_seconds * RATE)
        self.tail = int(tail_seconds * RATE)
        self.previous: list[Word] = []
        self.history: deque[Word] = deque(maxlen=256)
        self.cursor = 0
        self.revision = 0
        self.last_end = -1
        self.cursor_margin = int(0.04 * RATE)

    def _uncommitted(self, words: list[Word]) -> list[Word]:
        result = [w for w in words if w.end > self.cursor + self.cursor_margin]
        # Handle shifted timestamps at the committed/current boundary. Only remove
        # a repeated boundary word if its actual time interval overlaps history.
        while result and self.history:
            first, last = result[0], self.history[-1]
            if (normalize_word(first.text) == normalize_word(last.text) and
                    first.start < last.end and first.end <= last.end + self.tolerance // 2):
                result.pop(0)
            else:
                break
        return result

    def update(self, words: list[Word], window_end: int, endpoint: bool = False, window_start: int = 0,
               *, language: str | None = None) -> TranscriptUpdate:
        if window_end < self.last_end:
            raise ValueError("out-of-order ASR result")
        if len(words) > 1024:
            raise ValueError("unexpected ASR word count")
        if any(w.start < 0 or w.end < w.start or w.end > window_end + RATE for w in words):
            raise ValueError("invalid ASR word timestamps")
        if any(a.start > b.start for a, b in zip(words, words[1:])):
            raise ValueError("ASR words out of temporal order")
        self.last_end = window_end
        # Chinese/Japanese timestamp units are Unicode/token pieces, sometimes shorter
        # than the 40 ms tolerance used for space-delimited words.
        self.cursor_margin = 0 if language in NO_SPACE_LANGUAGES else int(0.04 * RATE)
        # If preview jobs were skipped, some earlier candidate words may have
        # left the rolling window before a second observation. Preserve them as
        # explicitly UNCONFIRMED boundary commits; never silently erase them or
        # label this fallback Local Agreement.
        expired = [w for w in self._uncommitted(self.previous) if w.end <= window_start]
        if expired:
            self.cursor = max(self.cursor, expired[-1].end)
            self.history.extend(expired)
        current = self._uncommitted(words)
        previous = self._uncommitted(self.previous)
        count = 0
        if current and previous:
            # Find the beginning of current in the previous timestamp interval.
            # No arbitrary character slicing; preserve compounds and genuine repeats.
            anchors = [i for i, w in enumerate(previous)
                       if normalize_word(w.text) == normalize_word(current[0].text)
                       and abs(w.start - current[0].start) <= self.tolerance]
            if anchors:
                best = min(anchors, key=lambda i: abs(previous[i].start - current[0].start))
                for old, new in zip(previous[best:], current):
                    if (normalize_word(old.text) != normalize_word(new.text) or
                            abs(old.start - new.start) > self.tolerance or new.end > window_end - self.tail):
                        break
                    count += 1
        reason = "local_agreement"
        if endpoint:
            count = len(current)
            reason = "endpoint_commit"  # explicitly distinguish single-pass tail commitment
        committed, candidate = current[:count], current[count:]
        if committed:
            self.cursor = max(self.cursor, committed[-1].end)
            self.history.extend(committed)
        self.previous = candidate
        self.revision += 1
        return TranscriptUpdate(self.revision, committed, candidate, reason, expired)
