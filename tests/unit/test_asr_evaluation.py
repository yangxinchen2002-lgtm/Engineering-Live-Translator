import pytest
pytest.importorskip('jiwer',reason='install evaluation extra to run reference scoring tests')
from app.asr.evaluation import read_cues,score,timestamp


def test_timestamp_and_vtt_srt(tmp_path):
    p=tmp_path/'reference.vtt'
    p.write_text('WEBVTT\n\n00:00.000 --> 00:02.000\n<v Professor>Eine Matrix.</v>\n\n00:03.000 --> 00:06.000\nZu spät.',encoding='utf-8')
    c=read_cues(p,5)
    assert len(c)==1 and c[0].text=='Eine Matrix.'
    assert timestamp('01:02:03,500')==3723.5
    with pytest.raises(ValueError):timestamp('00:62:00')


def test_wer_terms_and_errors():
    result=score('The state space is linear.','The state space is not linear.',['state space','linear'])
    assert result['wer']==pytest.approx(1/5)
    assert result['insertions']==1
    assert result['term_occurrence_accuracy']==1


def test_term_requires_aligned_exact_occurrence():
    result=score('Eigenwert und Eigenwert','Eigenwert und Eigenvektor',['Eigenwert'])
    assert result['term_occurrence_accuracy']==.5
    assert result['substitutions']==1


def test_term_precision_counts_extra_prompted_terms():
    result=score('Kernel und BIOS','Kernel und BIOS Kernel',['Kernel','BIOS'])
    assert result['term_occurrence_accuracy']==1
    assert result['term_occurrence_precision']==pytest.approx(2/3)
    assert result['terms'][0]['unmatched_hypothesis_occurrences']==1


def test_silence_and_hallucination_scoring():
    assert score('','hallucination',[])['insertions']==1
    assert score('real speech','',[])['deletions']==2


def test_duplicate_metric_distinguishes_revision_from_audio_repeat(tmp_path):
    import json
    from app.asr.evaluation import evaluate
    ref=tmp_path/'ref.srt';ref.write_text('1\n00:00:00,000 --> 00:00:02,000\nvery very',encoding='utf-8')
    log=tmp_path/'run.jsonl'
    events=[]
    for state,start,end in [('candidate',0,1000),('stable',0,1000),('stable',1100,2100),('committed',0,1000)]:
        events.append({'event':'transcript','state':state,'text':'very','words':[{'text':'very','start':start,'end':end}]})
    events.append({'event':'asr_summary','complete':True})
    log.write_text('\n'.join(json.dumps(e) for e in events),encoding='utf-8')
    result=evaluate(log,ref,3,[])
    assert result['duplicate_committed_word_events']==1
    assert result['committed_word_events']==3
    assert result['duplicate_audio_word_event_ratio']==pytest.approx(1/3)
