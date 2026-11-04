from dataclasses import replace
import numpy as np
import pytest
from app.asr.buffer import AudioRing
from app.asr.config import ASRConfig
from app.asr.language import LanguagePolicy
from app.asr.scheduler import Scheduler
from app.asr.stabilizer import TranscriptStabilizer, normalize_word
from app.asr.types import InputFrame, Word, RATE
from app.asr.vad import VadState


def words(text, offset=0, step=4000):
    return [Word(w, offset + i * step, offset + (i + 1) * step) for i,w in enumerate(text.split())]


@pytest.mark.parametrize("changes", [dict(language="es"), dict(window_seconds=0), dict(overlap_seconds=5),
    dict(buffer_seconds=1), dict(vad_negative_threshold=0.9), dict(language_probability_min=2),
    dict(schedule_seconds=float('nan')), dict(audio_queue_capacity=2.5)])
def test_invalid_config(changes):
    with pytest.raises(ValueError): replace(ASRConfig(), **changes).validate()


def test_config_unknown_rejected(tmp_path):
    p=tmp_path/'bad.toml';p.write_text('[asr]\nunknown = 1')
    with pytest.raises(ValueError): ASRConfig.load(p)
    assert ASRConfig.load(language='en').language=='en'


def test_ring_capacity_gaps_slices_and_clocks():
    ring=AudioRing(1)
    ring.append(InputFrame(0,np.ones(320,np.float32),20_000_000))
    assert ring.time_at(160)==10_000_000
    assert len(ring.slice(0,320))==320
    with pytest.raises(ValueError): ring.append(InputFrame(321,np.zeros(320,np.float32),40_000_000))
    with pytest.raises(BufferError): ring.append(InputFrame(320,np.zeros(16000,np.float32),0))
    ring.discard_before(100)
    assert ring.start==100 and ring.end==320
    with pytest.raises(BufferError): ring.slice(0,1)


def test_job_preserves_wall_clock_gap_when_no_audio_arrives_during_pause():
    ring=AudioRing(20)
    ring.append(InputFrame(0,np.zeros(RATE,np.float32),1_000_000_000))
    ring.append(InputFrame(RATE,np.zeros(RATE,np.float32),5_000_000_000))
    s=Scheduler(ASRConfig(),ring,lambda *a,**k:None)
    s.speech_start(0);s.advance(2*RATE)
    job=s.pop()
    assert job.time_at(RATE//2)==500_000_000
    assert job.time_at(RATE+RATE//2)==4_500_000_000


def test_vad_hysteresis_and_debounce():
    state=VadState(ASRConfig(min_speech_seconds=0.064,silence_seconds=0.064))
    assert state.update(.9,0)==[]
    event,=state.update(.9,512)
    assert event.kind=='start' and event.sample==0
    assert state.update(.4,1024)==[] and state.active
    assert state.update(.1,1536)==[]
    event,=state.update(.1,2048)
    assert event.kind=='end' and not state.active
    with pytest.raises(ValueError): state.update(float('nan'),2560)


def test_short_noise_does_not_start_speech():
    state=VadState(ASRConfig())
    for i,p in enumerate([.9,.1,.9,.1,.9,.1]):assert state.update(p,i*512)==[]


def test_language_lock_does_not_flip_on_foreign_term():
    policy=LanguagePolicy(ASRConfig(language='auto'))
    assert not policy.observe('de',.9,RATE)
    assert not policy.observe('de',.9,RATE+100)
    assert not policy.observe('de',.9,2*RATE)
    assert policy.observe('de',.9,3*RATE)
    assert not policy.observe('en',1.0,4*RATE) and policy.locked=='de'


def test_uncertain_or_unsupported_language_resets_votes():
    policy=LanguagePolicy(ASRConfig(language='auto'))
    policy.observe('de',.9,RATE);policy.observe('es',.99,2*RATE)
    assert policy.votes==0 and policy.locked is None
    assert LanguagePolicy(ASRConfig(language='en')).locked=='en'


def test_local_agreement_punctuation_and_compounds():
    s=TranscriptStabilizer(tail_seconds=0.01)
    assert not s.update(words('Der Zustandsraum ist'),30000).committed
    u=s.update(words('der Zustandsraum, ist linear.'),40000)
    assert [w.text for w in u.committed]==['der','Zustandsraum,','ist']
    assert [w.text for w in u.candidate]==['linear.']
    assert normalize_word('Übertragungsfunktion!')=='übertragungsfunktion'


def test_compound_revision_not_string_slicing():
    s=TranscriptStabilizer()
    s.update(words('Der Zustands raum'),30000)
    u=s.update(words('Der Zustandsraum ist linear'),40000)
    assert [w.text for w in u.committed]==['Der']
    assert u.candidate[0].text=='Zustandsraum'


def test_repeated_words_and_overlap_are_preserved_once():
    s=TranscriptStabilizer(tail_seconds=.01)
    w=words('very very small')
    s.update(w,30000)
    u=s.update(w,40000)
    assert [x.text for x in u.committed]==['very','very','small']
    u=s.update(w+words('indeed',12000),50000)
    assert not u.committed and [x.text for x in u.candidate]==['indeed']


def test_endpoint_is_not_labeled_local_agreement():
    s=TranscriptStabilizer()
    u=s.update(words('this is final'),20000,endpoint=True)
    assert len(u.committed)==3 and u.reason=='endpoint_commit' and not u.candidate


def test_skipped_preview_cannot_silently_erase_old_candidate():
    s=TranscriptStabilizer(tail_seconds=.01)
    s.update(words('one two three four five six'),30000)
    u=s.update(words('five six seven',16000),40000,window_start=16000)
    assert [w.text for w in u.expired]==['one','two','three','four']
    assert [w.text for w in u.committed]==['five','six']
    assert [w.text for w in u.candidate]==['seven']


def test_out_of_order_timestamps_rejected():
    s=TranscriptStabilizer();s.update(words('ok'),10000)
    with pytest.raises(ValueError): s.update(words('ok'),5000)
    with pytest.raises(ValueError): s.update([Word('bad',5000,1)],20000)


def scheduler_with_audio(seconds=8):
    ring=AudioRing(20);ring.append(InputFrame(0,np.zeros(int(seconds*RATE),np.float32),int(seconds*1e9)))
    events=[]
    cfg=ASRConfig(final_queue_capacity=2)
    return Scheduler(cfg,ring,lambda event,**data:events.append((event,data))),events


def test_preview_replacement_and_required_full_coverage():
    s,events=scheduler_with_audio(14)
    s.speech_start(0);s.advance(RATE);first=s.preview.id
    s.advance(2*RATE)
    assert s.skipped==1 and s.preview.id!=first
    s.advance(8*RATE)
    job=s.pop();assert job.required and (job.start,job.end)==(0,8*RATE)
    s.advance(14*RATE)
    job=s.pop();assert (job.start,job.end)==(6*RATE,14*RATE)
    assert any(e[0]=='preview_window_skipped' for e in events)


def test_mandatory_overflow_is_explicit():
    s,events=scheduler_with_audio(20)
    s.speech_start(0)
    with pytest.raises(BufferError): s.advance(20*RATE)
    assert events[-1][0]=='asr_backlog_overflow'
