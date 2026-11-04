"""Sentence ownership independent of Whisper segments and refill boundaries.

The decoder supplies right context. An unfinished relevant sentence asks for
more context before anything is translated. Hard bounds fall back visibly to a
clause/word boundary; no text is invented and timestamps remain source times.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .timeline import Cue, finite

RIGHT_CONTEXT = 8.0
MAX_DECODE_SPAN = 30.0
MAX_SENTENCE_SPAN = 30.0
MAX_CHARS = 760
MAX_WORDS = 160
PAUSE = 1.0
EDGE_GUARD = .45
_CLOSERS = '\"\'”’»）)]}'
_ABBREVIATIONS = {
    'dr.', 'prof.', 'mr.', 'mrs.', 'ms.', 'sr.', 'jr.', 'st.', 'no.', 'vs.',
    'e.g.', 'i.e.', 'etc.', 'fig.', 'eq.', 'approx.', 'z.b.', 'd.h.', 'bzw.',
    'usw.', 'u.a.', 'vgl.', 'ca.', 'nr.', 'abb.', 'bspw.', 'sog.',
}
_CONTINUATIONS = {
    'a','an','the','and','or','but','if','because','that','which','who','whose',
    'of','to','for','from','with','without','in','on','at','as','than','by',
    'und','oder','aber','wenn','weil','dass','daß','ob','obwohl','während',
    'damit','sodass','sowie','der','die','das','den','dem','des','ein','eine',
    'einer','eines','einem','einen','von','zu','zum','zur','für','mit','ohne',
    'im','am','beim','durch','als','nach','über','unter','zwischen',
}


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str


@dataclass
class SentencePlan:
    cues: list[Cue]
    preview: list[Cue]
    end: float
    needs_context: bool
    word_count: int


def text(words: list[Word]) -> str:
    # Whisper carries leading spaces; joining with extra spaces breaks CJK.
    return ''.join(w.text for w in words).strip()


def terminal(value: str) -> bool:
    value = value.rstrip().rstrip(_CLOSERS)
    if not value or value.endswith(('...', '…')):
        return False
    if value[-1] in '?!。！？':
        return True
    if not value.endswith('.'):
        return False
    token = value.split()[-1].lower()
    if token in _ABBREVIATIONS or re.fullmatch(r'(?:[a-z]\.)+', token):
        return False
    # A numeric token followed by a dot can be a German ordinal/list number.
    return not re.fullmatch(r'\d+\.', token)


def clause(left: Word, right: Word) -> bool:
    return (left.text.rstrip().rstrip(_CLOSERS).endswith((',', ';', ':', '，', '；', '：'))
            or right.start-left.end >= .25)


def pause_can_end(value: str) -> bool:
    value=value.rstrip().rstrip(_CLOSERS)
    if not value or value.endswith((',', ';', ':', '，', '；', '：')):
        return False
    return value.split()[-1].lower() not in _CONTINUATIONS


def extract_words(segments, begin: float, audio_start: float, audio_end: float) -> list[Word]:
    result = []
    for segment in segments:
        for word in segment.words or []:
            start = finite(audio_start+word.start, 0, 86400)
            end = finite(audio_start+word.end, start, 86400)
            if not isinstance(word.word, str):
                raise ValueError('invalid ASR word text')
            if begin <= (start+end)/2 < audio_end and word.word.strip() and end > start:
                result.append(Word(max(begin,start), min(audio_end,end), word.word))
    if any(a.start>b.start+.025 for a,b in zip(result,result[1:])):
        raise ValueError('out-of-order ASR words')
    return result


def _bounded(words: list[Word], reason: str):
    """Prefer a late clause boundary only when a genuinely long unit hits a cap."""
    while words:
        count = 0
        for i in range(1,len(words)+1):
            if (i>MAX_WORDS or len(text(words[:i]))>MAX_CHARS
                    or words[i-1].end-words[0].start>MAX_SENTENCE_SPAN):
                break
            count=i
        if not count:
            raise ValueError('ASR word exceeds sentence capacity')
        if count==len(words):
            yield words,reason
            return
        choices=[i for i in range(1,count+1) if i<len(words) and clause(words[i-1],words[i])
                 and words[i-1].end-words[0].start>=4]
        cut=choices[-1] if choices else count
        yield words[:cut], 'long_clause' if choices else 'limit'
        words=words[cut:]


def plan_sentences(segments, begin: float, target_end: float, audio_start: float,
                   audio_end: float, duration: float, generation: int,
                   *, allow_fallback: bool = False) -> SentencePlan:
    words=extract_words(segments,begin,audio_start,audio_end)
    eof=audio_end>=duration-.025
    groups=[];pending=[]
    for index,word in enumerate(words):
        pending.append(word)
        nxt=words[index+1] if index+1<len(words) else None
        gap=(nxt.start if nxt else audio_end)-word.end
        # A period hallucinated at the cut edge is not a confirmed sentence end.
        confirmed=nxt is not None or eof or audio_end-word.end>=EDGE_GUARD
        reason=('punctuation' if terminal(word.text) and confirmed
                else 'pause' if gap>=PAUSE and pause_can_end(word.text) else '')
        if reason:
            groups.append((pending,reason));pending=[]
    if pending:
        groups.append((pending,'eof' if eof else ''))

    cues=[];preview=[];needs_context=False;coverage=target_end
    def append(group,reason,complete=True):
        for part,boundary in _bounded(group,reason):
            cue=Cue(f'{generation}-{round(begin*1000)}-{round(part[0].start*1000)}',
                    part[0].start,part[-1].end,text(part),boundary=boundary,
                    complete_sentence=complete and boundary not in ('long_clause','limit'))
            preview.append(cue)
            if complete:cues.append(cue)

    for group,reason in groups:
        if group[0].start>=target_end:
            break  # Right context is evidence, not a second translation owner.
        if reason:
            append(group,reason)
            coverage=max(coverage,group[-1].end)
            continue
        if not allow_fallback:
            needs_context=True
            append(group,'pending',False)
        else:
            choices=[i for i in range(1,len(group)) if clause(group[i-1],group[i])
                     and group[i-1].end-group[0].start>=8]
            cut=choices[-1] if choices else len(group)
            append(group[:cut],'long_clause' if choices else 'limit')
            # Leave the rest for the next job starting at this exact word end.
            coverage=cues[-1].end
        break
    if cues and not needs_context:
        coverage=max(coverage,cues[-1].end)
    if coverage<=begin:
        raise ValueError('sentence preparation made no progress')
    return SentencePlan(cues,preview,min(duration,coverage),needs_context,len(words))
