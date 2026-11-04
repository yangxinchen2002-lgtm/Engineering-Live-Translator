import numpy as np
import pytest
from app.audio.processes import ProcessInfo, identity_changes, select_process
from app.audio.diagnostics import AudioDiagnostics
from app.main import generate_tones


def test_select_and_restart():
    a = ProcessInfo(1, "vlc.exe", r"C:\VLC\vlc.exe", 100)
    b = ProcessInfo(2, "vlc.exe", a.path, 101)
    assert select_process([a]) == a
    assert select_process([a, b], 2) == b
    for processes, pid in [([], None), ([a, b], None), ([a], 9)]:
        with pytest.raises(ValueError):
            select_process(processes, pid)
    reused = ProcessInfo(1, a.name, a.path, 102)
    assert identity_changes([a], [reused]) == {"exited": [a], "started": [reused]}


@pytest.mark.parametrize("leak,expected", [(0, True), (0.001, True), (0.1, False)])
def test_spectrum_isolation(leak, expected):
    t = np.arange(32000) / 16000
    samples = (0.25 * (np.sin(2 * np.pi * 1000 * t) + leak * np.sin(2 * np.pi * 440 * t))).astype(np.float32)
    d = AudioDiagnostics()
    for chunk in np.array_split(samples, 100):
        d.update(chunk)
    assert d.isolation_passes() is expected
    assert len(d._pending) < 16000
    assert d.summary()["rms"] > 0.17
    assert d.summary()["last_peak_hz"] == 1000


def test_silence_never_passes_isolation():
    d = AudioDiagnostics()
    d.update(np.zeros(32000, np.float32))
    assert not d.isolation_passes()
    assert d.summary()["leakage_db"] is None


def test_zero_db_worst_window_is_never_reset():
    d = AudioDiagnostics()
    d.worst_ratio_db = 0.0
    t = np.arange(16000) / 16000
    d.update(np.sin(2 * np.pi * 1000 * t).astype(np.float32))
    assert d.worst_ratio_db == 0.0
    assert not d.isolation_passes()


def test_frequency_drift_is_inconclusive_without_widening_threshold():
    d = AudioDiagnostics()
    t = np.arange(16000) / 16000
    d.update(np.sin(2 * np.pi * 1008 * t).astype(np.float32))
    assert d.summary()["last_peak_hz"] == 1008
    assert not d.isolation_passes()
    assert d.isolation_status() == "inconclusive_target_frequency_outside_band"


def test_tones_are_explicit_and_refuse_overwrite(tmp_path):
    import wave
    generate_tones(tmp_path, 1)
    with wave.open(str(tmp_path / "tone-1000hz.wav")) as w:
        assert w.getframerate() == 48000 and w.getnframes() == 48000
    with pytest.raises(FileExistsError):
        generate_tones(tmp_path, 1)
