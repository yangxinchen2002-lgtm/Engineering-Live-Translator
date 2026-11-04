import json
import pytest
pytest.importorskip('jiwer',reason='install evaluation extra to run reference scoring tests')
from app.asr.latency_evaluation import reference_latency


def test_reference_latency_counts_missed_cues_in_deadline_coverage(tmp_path):
    ref=tmp_path/'ref.srt'
    ref.write_text('1\n00:00:00,000 --> 00:00:01,000\none two\n\n2\n00:00:02,000 --> 00:00:03,000\nmissing phrase',encoding='utf-8')
    log=tmp_path/'run.jsonl'
    common={'event':'transcript','audio_end_ns':1_000_000_000,'end_sample':16000,
            'words':[{'text':'one','start':0,'end':8000},{'text':'two','start':8000,'end':16000}]}
    records=[{'event':'asr_session','realtime':True},
             {**common,'state':'candidate','displayed_ns':1_500_000_000},
             {**common,'state':'stable','displayed_ns':2_000_000_000}]
    log.write_text('\n'.join(json.dumps(r) for r in records),encoding='utf-8')
    r=reference_latency(log,ref,4)
    assert r['matched_preview']['p50']==.5
    assert r['matched_stable_agreement']['p50']==1
    assert r['reference_cues']==2 and r['fully_matched_cues']==1
    assert r['all_cue_preview_within_2s_fraction']==.5
    records[0]['realtime']=False
    log.write_text('\n'.join(json.dumps(r) for r in records),encoding='utf-8')
    with pytest.raises(ValueError):reference_latency(log,ref,4)
