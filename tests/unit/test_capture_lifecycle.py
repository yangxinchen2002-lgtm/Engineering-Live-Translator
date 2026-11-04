from pathlib import Path
import pytest
from app.audio.capture import CaptureSession
from app.audio.protocol import Kind, ProtocolError, control


class Pipe:
    def __init__(self, packets):
        self.packets = iter(packets)
        self.sent = []
        self.closed = False
    def receive(self):
        return next(self.packets)
    def send(self, packet):
        self.sent.append(packet)
    def close(self):
        self.closed = True


def bare_session(packets=()):
    session = CaptureSession.__new__(CaptureSession)
    session.pipe = Pipe(packets)
    session.child = None
    session._rx_sequence = session._tx_sequence = 0
    session._stopping = False
    session.stderr = ""
    return session


def test_sequence_gap_and_unexpected_type():
    for packet in [control(Kind.STATUS, 1), control(Kind.START, 0)]:
        with pytest.raises(ProtocolError):
            bare_session([packet]).receive()


def test_stop_idempotent_and_close():
    session = bare_session([control(Kind.STATUS, 0), control(Kind.STATUS, 1)])
    assert session.receive().sequence == 0
    assert session.receive().sequence == 1
    session.stop()
    session.stop()
    pipe = session.pipe
    assert len(pipe.sent) == 1 and pipe.sent[0].kind == Kind.STOP
    session.close()
    session.close()
    assert pipe.closed


def test_reap_after_timeout():
    import subprocess
    class Child:
        def __init__(self):
            self.calls = self.terminated = self.killed = 0
            self.returncode = -1
        def communicate(self, timeout):
            self.calls += 1
            if self.calls < 3:
                raise subprocess.TimeoutExpired("test-helper", timeout)
            return None, b"diagnostic"
        def terminate(self): self.terminated += 1
        def kill(self): self.killed += 1
    session = bare_session()
    session.child = Child()
    child = session.child
    session.close()
    assert child.terminated == child.killed == 1
    assert session.child is None and session.returncode == -1
    assert session.stderr == "diagnostic"


def test_missing_helper_is_real_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        CaptureSession(tmp_path / "missing.exe", None)
