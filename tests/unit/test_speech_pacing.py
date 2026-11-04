from dataclasses import replace
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from app.speech.pacing import CatchUpPacer
from app.speech.config import SpeechConfig


@pytest.mark.parametrize('base',[.8,1.,1.25,1.8,2.])
def test_grace_ramp_and_relative_cap(base):
    pacer=CatchUpPacer();speeds=[]
    for step in range(151):
        speed=pacer.update(300,base,True,step*100_000_000);speeds.append(speed)
        assert base<=speed<=base*1.5
        if step<50:assert speed==base
    assert speeds[51]>base and speeds[51]<speeds[-1]
    assert speeds[-1]==pytest.approx(base*1.5)
    assert max(b-a for a,b in zip(speeds,speeds[1:]))<=base*.016+.0011


def test_filter_commands_are_not_changed_on_every_twenty_millisecond_tick():
    pacer=CatchUpPacer(80,1);last=1.25;changes=[]
    for step in range(501):
        speed=pacer.update(300,1.25,True,step*20_000_000)
        if speed!=last:changes.append(step*20_000_000)
        last=speed
    assert changes and all(b-a>=200_000_000 for a,b in zip(changes,changes[1:]))


def test_short_spikes_and_threshold_chatter_never_start_acceleration():
    pacer=CatchUpPacer()
    for second in range(60):
        assert pacer.update(81 if second%4 else 79,1.25,True,second*1_000_000_000)==1.25
        assert not pacer.active


def test_more_pending_text_increases_tempo_and_hysteresis_avoids_restarts():
    pacer=CatchUpPacer()
    for step in range(121):low=pacer.update(100,1.,True,step*100_000_000)
    assert 1<low<1.5 and pacer.active
    for step in range(121,201):high=pacer.update(300,1.,True,step*100_000_000)
    assert high>low and high==1.5
    for step in range(201,241):
        pacer.update(70 if step%2 else 90,1.,True,step*100_000_000)
        assert pacer.active and pacer.above_since is None
    for step in range(241,301):last=pacer.update(0,1.,True,step*100_000_000)
    assert last==1 and not pacer.active


def test_disabling_catch_up_restores_manual_speed_and_new_session_resets_grace():
    pacer=CatchUpPacer()
    for step in range(151):pacer.update(400,2.,True,step*100_000_000)
    assert pacer.multiplier==1.5
    assert pacer.update(400,1.4,False,16_000_000_000)==1.4
    assert not pacer.active and pacer.multiplier==1
    assert pacer.update(400,1.4,True,20_000_000_000)==1.4
    with pytest.raises(ValueError):pacer.update(400,1.4,True,19_000_000_000)


def test_controller_counts_unstarted_text_and_excludes_playing_sentence(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.ui.speech import SpeechController
    from collections import deque
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True)
    speech.queue.append(('需要等待。'*20,0))
    speech.prefetched.append({'text':'还有下一句。','queued_ns':0})
    speech.current={'text':'当前句子。','playing':False,'raw':deque()}
    assert speech._backlog_characters()==89
    speech.current['playing']=True
    assert speech._backlog_characters()==85
    now=[0];monkeypatch.setattr('app.ui.speech.now_ns',lambda:now[0])
    assert speech._desired_speed()==1.25  # Loading/reserve time never triggers catch-up.
    now[0]=60_000_000_000;assert speech._desired_speed()==1.25
    speech.catch_up_started=True;assert speech._desired_speed()==1.25
    now[0]+=4_000_000_000;assert speech._desired_speed()==1.25
    now[0]+=1_000_000_000;assert speech._desired_speed()>1.25
    speech.stop();assert not speech.catch_up_started and not speech.pacer.active
    speech.close();app.processEvents()


@pytest.mark.parametrize('changes',[{'catch_up_start_chars':0},{'catch_up_start_chars':True},
    {'catch_up_grace_seconds':0},{'catch_up_grace_seconds':31}])
def test_invalid_pacing_settings_rejected(changes):
    with pytest.raises(ValueError):replace(SpeechConfig(),**changes).validate()
