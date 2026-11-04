import numpy as np
import pytest
from app.web_follow.alignment import RATE,match_audio


@pytest.mark.parametrize('offset',[-2.4,0,2.6])
def test_live_waveform_matches_known_source_position_with_independent_confirmation(offset):
    rng=np.random.default_rng(7);reference=rng.normal(0,.08,18*RATE).astype(np.float32)
    start=round((4.5+offset)*RATE);captured=reference[start:start+8*RATE].copy()
    captured+=rng.normal(0,.005,captured.size).astype(np.float32)
    result=match_audio(reference,captured,20,24.5)
    assert result['offset_seconds']==pytest.approx(offset,abs=.01)
    assert result['confirmations']==2 and result['correlation']>.9


def test_silence_or_repetitive_tone_cannot_be_reported_as_a_timing_measurement():
    silence=np.zeros(18*RATE,np.float32)
    with pytest.raises(ValueError,match='silent'):match_audio(silence,silence[:8*RATE],0,4.5)
    tone=(.1*np.sin(2*np.pi*440*np.arange(18*RATE)/RATE)).astype(np.float32)
    with pytest.raises(ValueError,match='ambiguous'):match_audio(tone,tone[:8*RATE],0,4.5)


def test_different_offsets_within_one_measurement_are_rejected():
    rng=np.random.default_rng(22);reference=rng.normal(0,.08,18*RATE).astype(np.float32)
    captured=reference[4*RATE:12*RATE].copy()
    captured[4*RATE:]=reference[10*RATE:14*RATE]
    with pytest.raises(ValueError,match='not stable'):match_audio(reference,captured,0,4.5)


def test_audio_target_is_an_active_session_inside_our_own_native_player(monkeypatch):
    from types import SimpleNamespace as NS
    import psutil
    from app.web_follow.alignment import own_player
    own=NS(pid=12,audio_state='active');other=NS(pid=99,audio_state='active')
    native=NS(pid=10,ppid=lambda:1,cmdline=lambda:['python','-m','app.web_follow.player'])
    gui=NS(cmdline=lambda:['python','-m','app.ui.main'],children=lambda **kw:[native])
    monkeypatch.setattr(psutil,'Process',lambda:NS(parents=lambda:[gui]))
    monkeypatch.setattr('app.audio.processes.ProcessSelector',lambda:NS(inspect=lambda pid:NS(pid=pid),
        discover=lambda kind:([other,own],[])))
    monkeypatch.setattr('app.audio.source_volume.process_tree',lambda *a:{10:None,12:None})
    assert own_player() is own


@pytest.mark.parametrize('offset',[2.024,-1.5])
def test_measured_timebase_moves_presentation_and_tts_deadline_without_changing_source(offset):
    from types import SimpleNamespace as NS
    from app.web_follow.server import Lab
    from app.web_follow.timeline import Cue
    lab=Lab()
    try:
        original=Cue('sentence',104,110,'Original sentence.',asr_confirmed=True,translation='原句。')
        lab.source=NS(remote=True);lab.options={'translate':True};lab.generation=NS(value=1);lab.raw_position=100
        lab.timeline.position=100;lab.timeline.prepared_until=120;lab.timeline.cues=[original]
        assert lab.apply_alignment(dict(status='measured',offset_seconds=offset,correlation=.9,peak_margin=.7,confirmations=2))
        browser_start=104-offset
        for position in np.arange(100,browser_start,1.):
            lab.clock(dict(position=float(position),paused=False,rate=1,seek=False))
        clock=dict(position=browser_start,paused=False,rate=1,seek=False)
        lab.clock(clock);state=lab.state();cue=state['cues'][0]
        assert state['position']==pytest.approx(browser_start)
        assert state['source_position']==pytest.approx(104)
        assert cue['start']==pytest.approx(browser_start) and cue['end']==pytest.approx(110-offset)
        assert cue['end']-state['position']==pytest.approx(6)  # Same complete speech slot.
        assert lab.timeline.cues[0] is original and original.start==104
        assert state['prepared_until']==pytest.approx(120-offset)
        assert clock['position']==browser_start  # Caller/original player is read-only.
        lab.clock(dict(position=500,paused=False,rate=1,seek=True))
        assert lab.timeline.position==pytest.approx(500+offset) and lab.state()['position']==pytest.approx(500)
    finally:lab.close()


def test_inconclusive_measurement_cannot_shift_subtitles_or_override_a_confirmed_mapping():
    from app.web_follow.server import Lab
    lab=Lab()
    try:
        result=dict(status='measured',offset_seconds=2,correlation=.9,peak_margin=.7,confirmations=2)
        assert not lab.apply_alignment({**result,'status':'inconclusive'})
        assert not lab.apply_alignment({**result,'correlation':.3})
        assert lab.clock_offset==0 and not lab.clock_calibrated
        assert lab.apply_alignment(result)
        assert not lab.apply_alignment({**result,'offset_seconds':-2}) and lab.clock_offset==2
    finally:lab.close()


def test_negative_offset_does_not_advance_browser_clock_at_start_of_video():
    from app.web_follow.server import Lab
    from app.web_follow.timeline import Cue
    lab=Lab()
    try:
        lab.timeline.cues=[Cue('first',0,2,'First sentence.')];lab.timeline.prepared_until=5
        assert lab.apply_alignment(dict(status='measured',offset_seconds=-1.5,correlation=.9,peak_margin=.7,confirmations=2))
        state=lab.state()
        assert state['position']==0 and state['cues'][0]['start']==1.5
    finally:lab.close()
