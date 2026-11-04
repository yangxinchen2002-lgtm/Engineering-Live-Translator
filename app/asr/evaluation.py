"""Reference-only evaluation; this module never calls an ASR model."""
from __future__ import annotations
from collections import Counter
from collections import deque
from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
import unicodedata


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def timestamp(value: str) -> float:
    values = value.replace(",", ".").split(":")
    if len(values) == 2:
        values.insert(0, "0")
    if len(values) != 3:
        raise ValueError(f"invalid subtitle timestamp: {value}")
    h, m, s = map(float, values)
    if h < 0 or not 0 <= m < 60 or not 0 <= s < 60:
        raise ValueError("invalid subtitle timestamp range")
    return h * 3600 + m * 60 + s


def read_cues(path: Path, seconds: float) -> list[Cue]:
    cues = []
    body = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    for block in re.split(r"\n\s*\n", body):
        lines = block.splitlines()
        for i, line in enumerate(lines):
            match = re.match(r"(\d[\d:,.]+)\s+-->\s+(\d[\d:,.]+)", line)
            if match:
                start, end = map(timestamp, match.groups())
                if end < start:
                    raise ValueError("subtitle end precedes start")
                text = html.unescape(re.sub(r"<[^>]+>", "", " ".join(lines[i + 1:])))
                # Only explicit non-speech labels; no number expansion or guessed paraphrases.
                text = re.sub(r"\[(?:APPLAUSE|LAUGHTER|MUSIC|Applaus|Musik|Lachen)\]", "", text, flags=re.I)
                if text.strip() and start < seconds and end <= seconds:
                    cues.append(Cue(start, end, text.strip()))
                break
    if not cues:
        raise ValueError("no subtitle cues in requested interval")
    return cues


def tokens(text: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)*", unicodedata.normalize("NFKC", text).casefold(), re.UNICODE)


def score(reference: str, hypothesis: str, terms: list[str]) -> dict:
    from jiwer import process_words
    ref, hyp = tokens(reference), tokens(hypothesis)
    result = process_words(" ".join(ref), " ".join(hyp))
    equal = {}
    for chunk in result.alignments[0]:
        if chunk.type == "equal":
            for r, h in zip(range(chunk.ref_start_idx, chunk.ref_end_idx), range(chunk.hyp_start_idx, chunk.hyp_end_idx)):
                equal[r] = h
    term_scores = []
    for term in terms:
        needle = tokens(term)
        positions = [i for i in range(len(ref) - len(needle) + 1) if ref[i:i + len(needle)] == needle] if needle else []
        correct = sum(all(i+j in equal for j in range(len(needle))) and
                      all(equal[i+j] == equal[i]+j for j in range(len(needle))) for i in positions)
        hyp_count = sum(hyp[i:i+len(needle)] == needle for i in range(len(hyp)-len(needle)+1)) if needle else 0
        term_scores.append({"term": term, "reference_occurrences": len(positions), "aligned_exact_occurrences": correct})
        term_scores[-1].update(hypothesis_occurrences=hyp_count, unmatched_hypothesis_occurrences=hyp_count-correct)
    total = sum(t["reference_occurrences"] for t in term_scores)
    correct = sum(t["aligned_exact_occurrences"] for t in term_scores)
    predicted = sum(t['hypothesis_occurrences'] for t in term_scores)
    def trigrams(values):
        return Counter(tuple(values[i:i+3]) for i in range(len(values)-2))
    excess = sum((trigrams(hyp) - trigrams(ref)).values())
    return {"reference_words": len(ref), "hypothesis_words": len(hyp), "wer": result.wer,
            "substitutions": result.substitutions, "deletions": result.deletions, "insertions": result.insertions,
            "term_occurrence_accuracy": correct / total if total else None, "terms": term_scores,
            "term_occurrence_precision": correct / predicted if predicted else None,
            "term_metric_note": "accuracy is matched reference occurrence recall; precision also checks unmatched predicted terms",
            "excess_hypothesis_trigrams": excess,
            "excess_trigram_ratio": excess / max(1,len(hyp)-2),
            "duplicate_metric_note": "excess 3-grams vs reference includes ASR mistakes; not a calibrated duplicate-subtitle rate",
            "normalization": "Unicode NFKC/casefold; punctuation removed; numbers not expanded"}


def evaluate(log: Path, reference: Path, seconds: float, terms: list[str]) -> dict:
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    summaries = [r for r in rows if r["event"] == "asr_summary"]
    if not summaries or not summaries[-1]["complete"]:
        raise ValueError("cannot score incomplete ASR run as successful")
    committed = [r for r in rows if r["event"] == "transcript" and r["state"] in ("stable", "committed")]
    cues = read_cues(reference, seconds)
    reference_text = " ".join(c.text for c in cues)
    hypothesis = " ".join(r["text"] for r in committed)
    from .stabilizer import normalize_word
    history = deque(maxlen=256)
    duplicate_words = word_events = 0
    for event in committed:
        for word in event['words']:
            key = normalize_word(word['text'])
            if not key:
                continue
            start, end = word['start'], word['end']
            def same_audio(old):
                old_key, old_start, old_end = old
                if old_key != key:
                    return False
                if start == end or old_start == old_end:
                    return start == old_start and end == old_end
                overlap = max(0, min(end, old_end) - max(start, old_start))
                return overlap / min(end-start, old_end-old_start) > .5
            duplicate_words += int(any(same_audio(old) for old in history))
            word_events += 1
            history.append((key,start,end))
    return {"reference_file": str(reference.resolve()), "transcript_log": str(log.resolve()),
            "requested_audio_seconds": seconds, "reference_cues": len(cues), "last_reference_end": cues[-1].end,
            "score": score(reference_text, hypothesis, terms), "run": summaries[-1],
            "duplicate_committed_word_events": duplicate_words, "committed_word_events": word_events,
            "duplicate_audio_word_event_ratio": duplicate_words / max(1,word_events),
            "duplicate_measurement_note": "same normalized word with >50% overlapping reported audio interval (or identical zero interval); timing-based proxy, not human adjudicated",
            "reference_quality_note": "publisher reference; verify human correction status from material manifest; do not equate with audited gold"}
