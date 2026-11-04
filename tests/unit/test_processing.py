from dataclasses import replace
import numpy as np
import pytest
from scipy.signal import upfirdn
from app.audio.processing import AudioProcessor, StreamingResampler, to_mono
from app.audio.protocol import Kind, Packet, ProtocolError, SampleFormat


def pcm(data, rate=48000, channels=1, fmt=SampleFormat.F32, first=0, flags=0):
    return Packet(Kind.AUDIO, rate=rate, channels=channels, format=fmt, frames=len(data) // channels,
                  first_sample=first, timestamp=first * 10_000_000 // rate, flags=flags,
                  valid_bits={SampleFormat.S16: 16, SampleFormat.S24: 24}.get(fmt, 32),
                  payload=np.asarray(data, dtype={SampleFormat.S16: "<i2", SampleFormat.S32: "<i4"}.get(fmt, "<f4")).tobytes())


@pytest.mark.parametrize("fmt,values,expected", [
    (SampleFormat.S16, [-32768, 0, 32767], [-1, 0, 32767 / 32768]),
    (SampleFormat.S32, [-2147483648, 0, 2147483647], [-1, 0, 1]),
    (SampleFormat.F32, [-0.5, 0, 0.75], [-0.5, 0, 0.75]),
])
def test_pcm(fmt, values, expected):
    np.testing.assert_allclose(to_mono(pcm(values, fmt=fmt)), expected, atol=1e-7)


def test_packed_24bit():
    p = Packet(Kind.AUDIO, rate=44100, channels=1, format=SampleFormat.S24, frames=3,
               valid_bits=24, payload=bytes.fromhex("000080000000ffff7f"))
    np.testing.assert_allclose(to_mono(p), [-1, 0, 8388607 / 8388608])


def test_left_aligned_24_in_32():
    p = replace(pcm([-2147483648, 1073741824], fmt=SampleFormat.S32), valid_bits=24)
    np.testing.assert_array_equal(to_mono(p), [-1, 0.5])


def test_stereo_mix():
    np.testing.assert_allclose(to_mono(pcm([1, -1, 0.5, 0.25], channels=2)), [0, 0.375])


def test_nonfinite_rejected():
    with pytest.raises(ProtocolError):
        to_mono(pcm([np.nan]))


@pytest.mark.parametrize("rate", [16000, 44100, 48000, 96000, 8000])
def test_streaming_resampling_matches_full_causal_filter(rate):
    rng = np.random.default_rng(42)
    x = rng.normal(size=rate // 2 + 137).astype(np.float32)
    r = StreamingResampler(rate)
    chunks = []
    i = 0
    while i < len(x):
        size = int(rng.integers(1, 947))
        chunks.append(r.process(x[i:i + size]))
        i += size
        assert len(r._history) < (len(r.taps) + r.up - 1) // r.up + r.down
    y = np.concatenate(chunks)
    n = (len(x) * 16000 + rate - 1) // rate
    assert len(y) == n
    np.testing.assert_allclose(y, upfirdn(r.taps, x, up=r.up, down=r.down)[:n], atol=2e-7)


@pytest.mark.parametrize("rate", [44100, 48000])
def test_resampling_rejects_alias_and_preserves_tone(rate):
    t = np.arange(rate) / rate
    def amplitude(freq):
        y = StreamingResampler(rate).process(np.sin(2 * np.pi * freq * t).astype(np.float32))
        return np.sqrt(np.mean(y[100:] ** 2))
    assert amplitude(1000) == pytest.approx(2 ** -0.5, abs=0.005)
    assert amplitude(12000) < 0.002


def test_frames_and_final_tail():
    processor = AudioProcessor()
    frames = processor.process(pcm(np.ones(1000), rate=16000))
    assert [f.start_sample for f in frames] == [0, 320, 640]
    assert all(len(f.samples) == 320 and f.samples.dtype == np.float32 for f in frames)
    tail, = processor.finish()
    assert tail.start_sample == 960 and len(tail.samples) == 40
    assert processor.finish() == []


@pytest.mark.parametrize("change", [dict(first_sample=99), dict(flags=1), dict(flags=4),
                                    dict(rate=44100), dict(timestamp=0)])
def test_gap_and_format_error(change):
    processor = AudioProcessor()
    processor.process(pcm(np.zeros(960)))
    second = replace(pcm(np.zeros(960), first=960), **change)
    if change == dict(timestamp=0):
        processor.process(pcm(np.zeros(960), first=960))
        second = replace(pcm(np.zeros(960), first=1920), timestamp=0)
    with pytest.raises(ProtocolError):
        processor.process(second)


def test_initial_discontinuity_is_stream_origin():
    AudioProcessor().process(pcm(np.zeros(960), flags=1))
