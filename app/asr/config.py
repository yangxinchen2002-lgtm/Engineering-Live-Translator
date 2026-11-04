from __future__ import annotations
from dataclasses import asdict, dataclass, fields
from pathlib import Path
import math
import tomllib
from app.languages import ASR_LANGUAGES

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ASRConfig:
    model: str = str(ROOT / "models/large-v3-turbo")
    device: str = "cuda"
    compute_type: str = "float16"
    language: str = "de"
    course_terms: str | None = None
    window_seconds: float = 8.0
    overlap_seconds: float = 2.0
    schedule_seconds: float = 1.0
    min_window_seconds: float = 1.0
    pre_roll_seconds: float = 0.3
    silence_seconds: float = 0.7
    min_speech_seconds: float = 0.16
    vad_threshold: float = 0.5
    vad_negative_threshold: float = 0.35
    stable_tail_seconds: float = 0.3
    timestamp_tolerance_seconds: float = 0.6
    buffer_seconds: float = 16.0
    final_queue_capacity: int = 3
    audio_queue_capacity: int = 256
    inference_timeout_seconds: float = 30.0
    startup_timeout_seconds: float = 180.0
    language_lock_votes: int = 3
    language_probability_min: float = 0.8
    gpu_poll_seconds: float = 1.0

    def validate(self) -> ASRConfig:
        if self.language not in ASR_LANGUAGES:
            raise ValueError(f"language must be one of {', '.join(ASR_LANGUAGES)}")
        if self.course_terms is not None and (not isinstance(self.course_terms, str) or not self.course_terms.strip()):
            raise ValueError('course_terms must be a path string or omitted')
        if self.device not in ("cuda", "cpu") or self.compute_type not in ("float16", "int8_float16", "int8", "float32"):
            raise ValueError("invalid explicit inference device/compute_type")
        for key, value in asdict(self).items():
            if isinstance(value, (float, int)) and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{key} must be finite and positive")
        for key in ("final_queue_capacity", "audio_queue_capacity", "language_lock_votes"):
            if type(getattr(self, key)) is not int:
                raise ValueError(f"{key} must be an integer")
        if not 0 < self.vad_negative_threshold < self.vad_threshold < 1:
            raise ValueError("VAD thresholds must be 0 < negative < threshold < 1")
        if not self.min_window_seconds <= self.window_seconds <= 30:
            raise ValueError("window must be between min_window_seconds and 30 s")
        if self.overlap_seconds >= self.window_seconds / 2 or self.schedule_seconds > self.window_seconds:
            raise ValueError("overlap must be less than half window; schedule <= window")
        if self.buffer_seconds < self.window_seconds + self.overlap_seconds + 1:
            raise ValueError("buffer too small for window/context")
        if self.final_queue_capacity > 20 or self.audio_queue_capacity > 5000:
            raise ValueError("queue capacity exceeds supported bound")
        if self.language_probability_min > 1:
            raise ValueError("invalid language detection threshold")
        return self

    @classmethod
    def load(cls, path: Path | None = None, **overrides) -> ASRConfig:
        data = {}
        if path:
            data = tomllib.loads(path.read_text(encoding="utf-8")).get("asr", {})
        allowed = {f.name for f in fields(cls)}
        if data.keys() - allowed:
            raise ValueError(f"unknown ASR settings: {sorted(data.keys() - allowed)}")
        data.update({k: v for k, v in overrides.items() if v is not None})
        if data.get('course_terms') == '':
            data['course_terms'] = None  # explicit --no-course-terms override
        elif isinstance(data.get('course_terms'), str):
            base = path.resolve().parent if path else ROOT
            data['course_terms'] = str((base / data['course_terms']).resolve())
        return cls(**data).validate()
