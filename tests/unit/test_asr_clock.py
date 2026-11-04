import time
import pytest
from app.asr.clock import now_ns,metadata,validate_capture_timestamp,latency_seconds,sample_time


def test_m1_does_not_use_gettickcount_epoch(monkeypatch):
    monkeypatch.setattr(time,'monotonic_ns',lambda:0)
    t=now_ns()
    assert t>0 and metadata()['monotonic']
    validate_capture_timestamp(t//100,t)
    assert latency_seconds(t,t+1_000_000_000)==1


def test_mixed_epoch_and_negative_latency_are_errors():
    t=now_ns()
    with pytest.raises(ValueError):validate_capture_timestamp(t//100,t-36_000_000_000)
    with pytest.raises(ValueError):latency_seconds(t,t-36_000_000_000)


def test_expired_candidate_keeps_its_original_clock_after_window_roll():
    old=[(0,16000,1_000_000_000),(16000,32000,5_000_000_000)]
    current=[(32000,48000,6_000_000_000)]
    with pytest.raises(ValueError):sample_time(current,8000)
    assert sample_time(old+current,8000)==500_000_000
    assert sample_time(old+current,40000)==5_500_000_000
