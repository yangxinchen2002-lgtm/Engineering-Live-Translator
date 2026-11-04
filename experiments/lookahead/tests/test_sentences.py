from types import SimpleNamespace as NS

import pytest

from experiments.lookahead.sentences import plan_sentences,terminal
from experiments.lookahead.timeline import Timeline


def segment(*words):
    return NS(words=[NS(start=a,end=b,word=t) for a,b,t in words])


def plan(segments,end=6,audio_end=14,begin=0,duration=100,**kw):
    return plan_sentences(segments,begin,end,0,audio_end,duration,1,**kw)


def test_whisper_segment_boundaries_do_not_cut_a_sentence():
    result=plan([segment((0,1,'This'),(1,2,' is')),
                 segment((2,3,' one'),(3,4,' sentence.'))])
    assert [c.source for c in result.cues]==['This is one sentence.']
    assert not result.needs_context and result.cues[0].complete_sentence


def test_two_sentences_inside_one_segment_are_not_glued():
    result=plan([segment((0,1,'First'),(1,2,' sentence.'),(2.2,3,' Second'),(3,4,' sentence.'))])
    assert [c.source for c in result.cues]==['First sentence.','Second sentence.']


def test_sentence_crosses_refill_boundary_and_is_owned_once():
    segments=[segment((0,2,'A'),(2,5,' long'),(5,9,' sentence.'),(9.2,10,' Next'),(10,12,' sentence.'))]
    left=plan(segments)
    assert left.end==9 and left.cues[0].source=='A long sentence.'
    right=plan(segments,begin=left.end,end=15,audio_end=23)
    assert [c.source for c in right.cues]==['Next sentence.']
    timeline=Timeline();assert timeline.commit(1,0,left.end,left.cues)
    assert timeline.commit(1,left.end,right.end,right.cues)
    assert len(timeline.cues)==2


def test_unfinished_sentence_requests_more_audio_not_translation():
    result=plan([segment((0,3,'The'),(3,8,' condition'),(8,13.9,' is'))])
    assert result.needs_context and not result.cues
    assert result.preview[0].source=='The condition is'
    assert result.preview[0].boundary=='pending' and not result.preview[0].speech
    extended=plan([segment((0,3,'The'),(3,8,' condition'),(8,14,' is'),(14,17,' satisfied.'))],audio_end=30)
    assert not extended.needs_context and extended.end==17
    assert extended.cues[0].source=='The condition is satisfied.'


def test_period_at_audio_cut_requires_right_context():
    result=plan([segment((0,5,'A'),(5,13.9,' statement.'))])
    assert result.needs_context
    assert not result.cues  # Whisper's endpoint punctuation alone is not proof.


@pytest.mark.parametrize('value',['Dr.','Prof.','z.B.','d.h.','e.g.','i.e.','U.S.','A.','3.','...'])
def test_abbreviations_and_ordinals_are_not_sentence_ends(value):
    assert not terminal(value)


def test_decimal_abbreviations_and_sentence_end_together():
    result=plan([segment((0,.5,'Dr.'),(.5,1,' Smith'),(1,2,' uses'),(2,3,' 3.14'),(3,4,' here.'))])
    assert len(result.cues)==1 and result.cues[0].source=='Dr. Smith uses 3.14 here.'


def test_cjk_and_quoted_punctuation_preserve_original_spacing():
    result=plan([segment((0,1,'你好'),(1,2,'世界。'),(2,3,'次の文'),(3,4,'です。”'))])
    assert [c.source for c in result.cues]==['你好世界。','次の文です。”']


def test_real_pause_is_a_boundary_without_inventing_a_period():
    result=plan([segment((0,1,'That'),(1,2,' is all'),(3.2,4,'Next'),(4,5,' topic.'))])
    assert result.cues[0].source=='That is all' and result.cues[0].boundary=='pause'
    assert len(result.cues)==2


@pytest.mark.parametrize('tail',[' that',' dass',' condition,'])
def test_thinking_pause_after_connector_or_comma_keeps_the_sentence_together(tail):
    result=plan([segment((0,1,'We assume'),(1,2,tail),(3.5,5,' it holds.'))])
    assert len(result.cues)==1
    assert result.cues[0].boundary=='punctuation'


def test_eof_flushes_final_words_without_waiting_for_more_audio():
    result=plan([segment((0,1,'Final'),(1,4,' words'))],end=4,audio_end=4,duration=4)
    assert not result.needs_context and result.end==4 and result.cues[0].boundary=='eof'


def test_long_unpunctuated_speech_uses_late_clause_and_leaves_tail_unowned():
    words=[(i,i+.9,('word' if i==0 else ' word')+(',' if i==12 else '')) for i in range(30)]
    result=plan([segment(*words)],end=15,audio_end=30,allow_fallback=True)
    assert not result.needs_context and result.end==pytest.approx(12.9)
    assert result.cues[-1].boundary=='long_clause' and not result.cues[-1].complete_sentence
    assert len(result.cues[-1].source.split())==13


def test_no_punctuation_is_bounded_and_reported_not_silently_dropped():
    words=[(i,i+.99,'x' if i==0 else ' x') for i in range(30)]
    result=plan([segment(*words)],end=15,audio_end=30,allow_fallback=True)
    assert not result.needs_context
    assert sum(len(c.source.split()) for c in result.cues)==30
    assert all(c.boundary=='limit' and not c.complete_sentence for c in result.cues)
    assert all(c.end-c.start<=30 and len(c.source)<=760 for c in result.cues)


def test_silence_and_future_context_do_not_become_subtitles():
    assert plan([],end=6).end==6
    result=plan([segment((8,9,'Future'),(9,10,' sentence.'))])
    assert result.cues==[] and result.end==6


def test_large_grammatical_sentence_splits_at_clause_only_at_capacity():
    words=[(i*.1,i*.1+.09,('word' if i==0 else ' word')+(',' if i==100 else '')) for i in range(158)]
    words[-1]=(words[-1][0],words[-1][1],words[-1][2]+'.')
    result=plan([segment(*words)],end=20,audio_end=23)
    assert len(result.cues)==2
    assert result.cues[0].boundary=='long_clause'
    assert sum(len(c.source.split()) for c in result.cues)==158
