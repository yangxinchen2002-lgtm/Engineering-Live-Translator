"""Bounded retry for pathological decoder loops, not a correctness score."""
from collections import Counter
import re
from .types import Word, RATE
from app.languages import NO_SPACE_LANGUAGES


def pathological(text: str, audio_seconds: float) -> bool:
    tokens = re.findall(r"\w+", text.casefold())
    if len(tokens) < 24:
        return False
    repetitions = Counter(tuple(tokens[i:i+3]) for i in range(len(tokens)-2))
    return (len(tokens) / max(audio_seconds, 0.1) > 15 or
            (repetitions and max(repetitions.values()) >= 5 and len(set(tokens)) / len(tokens) < 0.3))


def decode(model, audio, language, *, hotwords: str | None = None):
    options = dict(language=language, task="transcribe", beam_size=1, temperature=0.0,
                   word_timestamps=True, vad_filter=False, condition_on_previous_text=False)
    if hotwords:
        options['hotwords'] = hotwords
    segments, info = model.transcribe(audio, **options)
    segments = list(segments)
    initial_text = "".join(s.text for s in segments).strip()
    retried = pathological(initial_text, len(audio) / 16000)
    if retried:
        # Do not truncate or regex-replace hallucinated words. Run the real model
        # once more with an explicit repetition guard and report the retry.
        segments, info = model.transcribe(audio, **options, repetition_penalty=1.05, no_repeat_ngram_size=4)
        segments = list(segments)
        if pathological("".join(s.text for s in segments), len(audio) / 16000):
            raise RuntimeError("pathological ASR repetition persists after bounded decoder retry")
    return segments, info, retried, len(initial_text.split())


def segment_words(segments, start: int, end: int, language: str | None = None) -> list[Word]:
    """Convert model-local timestamps to the unchanged global sample timeline."""
    words = []
    for segment in segments:
        for word in segment.words or []:
            begin = max(start, start + round(word.start * RATE))
            finish = min(end, start + round(word.end * RATE))
            if word.word.strip() and finish >= begin:
                words.append(Word(word.word, begin, finish))
    if language in NO_SPACE_LANGUAGES:
        # The aligner may give multiple Chinese/Japanese pieces the same end timestamp,
        # including zero-duration particles/punctuation. Keep their text in one
        # timestamp unit so sample-cursor deduplication cannot silently lose it.
        grouped = []
        for word in words:
            if grouped and (word.end <= grouped[-1].end or grouped[-1].start == grouped[-1].end):
                previous = grouped.pop()
                word = Word(previous.text + word.text, min(previous.start, word.start), max(previous.end, word.end))
            grouped.append(word)
        if any(word.start == word.end for word in grouped):
            raise RuntimeError('ASR alignment has no positive duration; transcription incomplete')
        return grouped
    return words
