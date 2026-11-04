"""Opt-in smoke only. A/B/C/D/E still require documented real playback procedures."""
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.hardware
@pytest.mark.skipif(os.environ.get("ELT_RUN_HARDWARE") != "1", reason="explicit live-audio opt-in required")
def test_live_native_to_python():
    helper = Path(os.environ["ELT_HELPER"])
    pid = os.environ["ELT_VLC_PID"]
    assert helper.is_file()
    result = subprocess.run([sys.executable, "-m", "app.main", "capture", "--helper", str(helper),
                             "--pid", pid, "--seconds", "5"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"signal_detected": true' in result.stdout
