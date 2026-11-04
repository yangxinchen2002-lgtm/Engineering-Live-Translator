from pathlib import Path
import threading
import wave

import httpx
import numpy as np
import pytest
from experiments.lookahead.media import Source, byte_range, decode_window, probe, repair_rounding
from experiments.lookahead.server import Lab, Server, options_from


@pytest.fixture
def tone(tmp_path):
    path = tmp_path / 'tone.wav'
    rate = 48000
    sample = (.2 * np.sin(2 * np.pi * 1000 * np.arange(rate * 3) / rate) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as f:
        f.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
        f.writeframes(np.column_stack([sample, sample]).tobytes())
    return path


def test_actual_resample_seek_and_spectrum(tone):
    source = Source.parse(str(tone))
    assert probe(source)['input_rate'] == 48000
    audio, metrics = decode_window(source, .75, 1.75)
    assert audio.dtype == np.float32 and audio.size == 16000
    spectrum = np.abs(np.fft.rfft(audio))
    assert np.argmax(spectrum) == 1000
    assert metrics['rms'] == pytest.approx(.2 / np.sqrt(2), abs=.002)
    assert metrics['missing_samples'] <= 2


def test_decoder_honors_cancellation(tone):
    with pytest.raises(InterruptedError):
        decode_window(Source.parse(str(tone)), 0, 1, lambda: True)


def test_seek_uses_audio_time_base(tone):
    audio, metrics = decode_window(Source.parse(str(tone)), 2.25, 2.75)
    frequencies = np.fft.rfftfreq(audio.size, 1 / 16000)
    assert frequencies[np.argmax(np.abs(np.fft.rfft(audio)))] == 1000
    assert metrics['missing_samples'] <= 2 and audio.size == 8000


def test_timestamp_rounding_repairs_are_explicit_and_larger_gaps_fail():
    audio = np.arange(32000, dtype=np.float32)
    covered = np.ones(32000, dtype=bool)
    covered[[10, 20, 30]] = False
    audio[~covered] = 0
    metrics = repair_rounding(audio, covered)
    assert metrics['rounding_repaired_samples'] == 3
    assert audio[10] == 10 and audio[20] == 20
    covered[50:53] = False
    with pytest.raises(ValueError, match='largest gap'):
        repair_rounding(audio, covered)


def test_seek_priming_frames_are_counted_only_before_valid_timestamps(monkeypatch):
    import av
    from contextlib import contextmanager
    from fractions import Fraction
    from types import SimpleNamespace as NS
    def frame(length, pts):
        f = av.AudioFrame.from_ndarray(np.full((1, length), .1, np.float32), format='fltp', layout='mono')
        f.sample_rate, f.pts, f.time_base = 16000, pts, Fraction(1,16000)
        return f
    frames = [frame(1024,None),frame(16000,0)]
    class Container:
        start_time = 0
        streams = NS(audio=[NS(codec_context=NS(sample_rate=16000,layout='mono',channels=1))])
        def decode(self, stream):
            yield from frames
    @contextmanager
    def opened(source):
        yield Container()
    monkeypatch.setattr('experiments.lookahead.media.open_media', opened)
    audio, metrics = decode_window(Source('test-only',False,'audio/wav'),0,1)
    assert metrics['discarded_priming_frames'] == 1 and metrics['missing_samples'] == 0
    assert np.allclose(audio,.1)
    frames[:] = [frame(8000,0),frame(1024,None),frame(8000,8000)]
    with pytest.raises(ValueError,match='timestamp unavailable'):
        decode_window(Source('test-only',False,'audio/wav'),0,1)


@pytest.mark.parametrize('value', ['blob:https://x/1', 'data:audio/wav,abc', 'file://x/a.mp4', 'ftp://x/a.mp4',
                                 'https://user:password@x/a.mp4', 'https://x/a.mp4#fragment'])
def test_source_rejects_unsupported_protocols(value):
    with pytest.raises((ValueError, OSError)):
        Source.parse(value)


@pytest.mark.parametrize('header,want', [(None, (0, 99)), ('bytes=0-0', (0, 0)), ('bytes=50-', (50, 99)),
                                        ('bytes=-20', (80, 99)), ('bytes=90-200', (90, 99))])
def test_ranges(header, want):
    assert byte_range(header, 100) == want


@pytest.mark.parametrize('header', ['bytes=100-', 'bytes=8-2', 'bytes=-0', 'bytes=0-1,3-4', 'bytes=-'])
def test_bad_ranges(header):
    with pytest.raises(ValueError):
        byte_range(header, 100)


def test_options_require_explicit_cloud_and_speech():
    assert not options_from({})['translate']
    with pytest.raises(ValueError):
        options_from({'narrate': True})
    with pytest.raises(ValueError):
        options_from({'provider': 'custom'})


def test_old_clock_or_previous_session_cannot_seek_backwards(tone):
    lab = Lab()
    try:
        lab.source = Source.parse(str(tone))
        lab.session_id = 'current'
        # A shared generation slot without spawning the model.
        from types import SimpleNamespace
        lab.generation = SimpleNamespace(value=lab.timeline.generation)
        lab.clock(dict(position=20, paused=True, rate=1, seek=True, sequence=2, session_id='current'))
        generation = lab.timeline.generation
        lab.clock(dict(position=2, paused=True, rate=1, seek=True, sequence=1, session_id='current'))
        lab.clock(dict(position=3, paused=True, rate=1, seek=True, sequence=100, session_id='previous'))
        assert lab.timeline.position == 20 and lab.timeline.generation == generation
    finally:
        lab.close()


def test_real_http_media_range_auth_and_shutdown(tone):
    lab = Lab()
    lab.source = Source.parse(str(tone))
    server = Server(lab)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=server.origin, trust_env=False) as client:
            assert client.get('/').status_code == 200
            assert client.get('/api/state').status_code == 403
            auth = {'X-ELT-Lab-Token': server.token}
            assert client.get('/api/state', headers=auth).status_code == 200
            assert client.post('/api/stop', headers={**auth, 'Origin': 'https://evil.example'}, json={}).status_code == 403
            assert client.get('/media?token=wrong').status_code == 403
            r = client.get('/media?token=' + server.token, headers={'Range': 'bytes=44-99'})
            assert r.status_code == 206 and r.content == tone.read_bytes()[44:100]
            assert r.headers['content-range'] == f'bytes 44-99/{tone.stat().st_size}'
            assert client.get('/media?token=' + server.token, headers={'Range':'bytes=999999-'}).status_code == 416
            assert client.get('/speech/../../secret?token=' + server.token).status_code == 403
            assert client.get('/sync.mjs').status_code == 200
            assert client.post('/api/clock', headers=auth, content='{"position":Infinity}').status_code == 400
    finally:
        server.shutdown()
        server.server_close()
        lab.close()
        thread.join(timeout=3)


def test_page_heartbeat_and_automatic_idle_exit():
    import time
    lab = Lab()
    server = Server(lab)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=server.origin, trust_env=False) as client:
            before = lab.last_seen
            response = client.post('/api/ping', headers={'X-ELT-Lab-Token':server.token}, json={})
            assert response.status_code == 200 and lab.last_seen >= before
        lab.last_seen = time.monotonic() - 61  # Test clock only; no actual minute-long wait.
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        if thread.is_alive():
            server.shutdown()
        server.server_close()
        lab.close()


def test_hls_proxy_hides_signed_links_and_forgets_stopped_source(monkeypatch):
    playlist = '#EXTM3U\n#EXTINF:6,\nhttps://media.example/part.ts?jwt=test-only\n#EXT-X-ENDLIST\n'
    monkeypatch.setattr('experiments.lookahead.server.fetch_manifest', lambda url: playlist)
    lab = Lab()
    lab.source = Source.parse('https://media.example/master.m3u8?jwt=test-only')
    lab.session_id = 'test-session'
    server = Server(lab)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=server.origin, trust_env=False) as client:
            response = client.get('/media?token=' + server.token)
            assert response.status_code == 200 and 'jwt=' not in response.text
            assert 'https://' not in response.text and len(lab.resources) == 1
            resource = next(line for line in response.text.splitlines() if line.startswith('/hls/'))
            assert client.post('/api/stop', headers={'X-ELT-Lab-Token':server.token}, json={}).status_code == 200
            assert lab.resources == {} and client.get(resource).status_code == 404
    finally:
        server.shutdown()
        server.server_close()
        lab.close()
