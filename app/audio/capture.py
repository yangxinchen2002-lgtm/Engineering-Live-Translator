from __future__ import annotations

from pathlib import Path
import subprocess
import uuid

from .processes import ProcessInfo, ProcessSelector, process_source
from .protocol import Kind, Packet, ProtocolError, control
from .transport import NamedPipe


class CaptureSession:
    """Single-use capture session. close() always reaps the child with bounded waits."""
    def __init__(self, helper: Path, target: ProcessInfo):
        if not helper.is_file():
            raise FileNotFoundError(f"build native helper first: {helper}")
        if ProcessSelector().inspect(target.pid) != target:
            raise RuntimeError("target identity changed; select the audio source again")
        source = process_source(target)
        self.child: subprocess.Popen | None = None
        self.pipe: NamedPipe | None = None
        self._rx_sequence = 0
        self._tx_sequence = 0
        self._stopping = False
        self.stderr = ""
        self.returncode: int | None = None
        name = rf"\\.\pipe\ELT-{uuid.uuid4().hex}"
        try:
            self.child = subprocess.Popen([str(helper.resolve()), "--pipe", name, "--pid", str(target.pid),
                                           "--created", str(target.created), "--source", source], stdin=subprocess.DEVNULL,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                          creationflags=subprocess.CREATE_NO_WINDOW)
            self.pipe = NamedPipe(name)
            self.pipe.send(control(Kind.START, self._tx_sequence))
            self._tx_sequence += 1
        except BaseException as exc:
            self.close()
            if self.stderr and isinstance(exc, Exception):
                raise RuntimeError(f"helper startup failed: {exc}; {self.stderr}") from exc
            raise

    def receive(self) -> Packet:
        assert self.pipe is not None
        packet = self.pipe.receive()
        if packet.sequence != self._rx_sequence:
            raise ProtocolError("IPC sequence gap/duplicate; audio may be incomplete")
        self._rx_sequence += 1
        if packet.kind not in (Kind.AUDIO, Kind.STATUS, Kind.ERROR):
            raise ProtocolError("unexpected native message type")
        return packet

    def stop(self) -> None:
        if not self._stopping and self.pipe:
            self.pipe.send(control(Kind.STOP, self._tx_sequence))
            self._tx_sequence += 1
            self._stopping = True

    def close(self) -> None:
        if self.pipe:
            self.pipe.close()
            self.pipe = None
        if self.child:
            try:
                _, err = self.child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                try:
                    _, err = self.child.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    _, err = self.child.communicate(timeout=3)
            self.stderr = err.decode("utf-8", errors="replace") if err else ""
            self.returncode = self.child.returncode
            # Release the Windows process HANDLE even if callers retain this session.
            self.child = None

    def __enter__(self) -> CaptureSession:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
