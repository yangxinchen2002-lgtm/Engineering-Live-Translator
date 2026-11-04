from __future__ import annotations
from collections import deque
import time
from .buffer import AudioRing
from .config import ASRConfig
from .types import ASRJob, RATE
from .clock import now_ns


class Scheduler:
    """Preview replacement + bounded mandatory windows. Mandatory audio is never dropped."""
    def __init__(self, config: ASRConfig, ring: AudioRing, emit):
        self.config, self.ring, self.emit = config, ring, emit
        self.required: deque[ASRJob] = deque()
        self.preview: ASRJob | None = None
        self.start: int | None = None
        self.last_scheduled = 0
        self.next_id = self.segment_id = 0
        self.skipped = 0
        self.completed_end = 0
        self.last_required_end = 0

    def speech_start(self, sample: int) -> None:
        if self.start is not None:
            return
        self.start = max(sample, self.ring.start)
        self.last_scheduled = self.start
        self.segment_id += 1

    def _job(self, start: int, end: int, required: bool, endpoint: bool) -> ASRJob:
        self.next_id += 1
        job = ASRJob(self.next_id, self.segment_id, start, end, self.ring.slice(start, end),
                     required, endpoint, self.ring.time_at(end), now_ns())
        job.clock_spans = [span for span in self.ring.clocks if span[1] >= start and span[0] <= end]
        return job

    def _skip_preview(self) -> None:
        if self.preview is not None:
            self.skipped += 1
            self.emit("preview_window_skipped", job_id=self.preview.id, start_sample=self.preview.start,
                      end_sample=self.preview.end, count=self.skipped)
            self.preview = None

    def _required(self, end: int, endpoint: bool) -> None:
        assert self.start is not None
        if end <= self.start:
            return
        if len(self.required) >= self.config.final_queue_capacity:
            self.emit("asr_backlog_overflow", queue_length=len(self.required),
                      unprocessed_start_sample=self.start, unprocessed_end_sample=end)
            raise BufferError("mandatory ASR queue full; audio processing incomplete")
        job = self._job(self.start, end, True, endpoint)
        if self.last_required_end and job.start > self.last_required_end:
            # Gaps between utterances are intentional VAD silence, identified in diagnostics.
            self.emit("vad_silence_skipped", start_sample=self.last_required_end, end_sample=job.start)
        self.last_required_end = end
        self.required.append(job)
        self._skip_preview()
        self.emit("asr_required_queued", job_id=job.id, start_sample=job.start, end_sample=job.end, endpoint=endpoint)

    def advance(self, end: int) -> None:
        if self.start is None:
            self.ring.discard_before(max(self.ring.start, end - RATE))
            return
        window = int(self.config.window_seconds * RATE)
        overlap = int(self.config.overlap_seconds * RATE)
        while end - self.start >= window:
            boundary = self.start + window
            self._required(boundary, False)
            self.start = boundary - overlap
            self.last_scheduled = boundary
        if (end - self.start >= int(self.config.min_window_seconds * RATE) and
                end - self.last_scheduled >= int(self.config.schedule_seconds * RATE)):
            self._skip_preview()
            self.preview = self._job(self.start, end, False, False)
            self.last_scheduled = end
        self.ring.discard_before(self.start)

    def speech_end(self, end: int) -> None:
        if self.start is not None:
            self._required(min(end, self.ring.end), True)
            self.start = None

    def pop(self) -> ASRJob | None:
        if self.required:
            return self.required.popleft()
        if self.preview and self.preview.end > self.completed_end:
            job, self.preview = self.preview, None
            return job
        self._skip_preview()
        return None

    def statistics(self) -> dict:
        pending = list(self.required) + ([self.preview] if self.preview else [])
        return {"pending_required": len(self.required), "pending_preview": int(self.preview is not None),
                "preview_windows_skipped": self.skipped,
                "oldest_wait_seconds": ((now_ns() - min(j.created_ns for j in pending)) / 1e9 if pending else 0)}
