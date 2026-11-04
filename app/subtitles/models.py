from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum


class SubtitleState(StrEnum):
    PREVIEW = 'preview'
    FINAL = 'final'


@dataclass(frozen=True)
class SourceWord:
    text: str
    start: int
    end: int
    start_ns: int = 0
    end_ns: int = 0


@dataclass(frozen=True)
class Subtitle:
    session_id: str
    segment_id: int
    revision: int
    source_language: str
    source_text: str
    translated_text: str
    start_sample: int
    end_sample: int
    state: SubtitleState = SubtitleState.PREVIEW
    candidate_text: str = ''
    candidate_revision: int = 0
    source_closed: bool = False
    close_reason: str = ''
    asr_stability: str = ''
    translation_status: str = 'waiting'
    translation_retry_pending: bool = False
    translated_revision: int = 0
    translation_source_text: str = ''
    active_attempt: str = ''
    completed_attempt: str = ''
    audio_end_ns: int = 0


@dataclass(frozen=True)
class TranslationRequest:
    session_id: str
    segment_id: int
    revision: int
    source_language: str
    source_text: str
    source_closed: bool
    start_sample: int
    end_sample: int
    audio_end_ns: int
    created_ns: int
