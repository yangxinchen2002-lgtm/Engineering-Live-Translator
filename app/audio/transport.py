"""Cancelable overlapped byte-mode named pipe client; one reader/one writer."""
from __future__ import annotations

import time
from .protocol import Packet, read_packet


class NamedPipe:
    def __init__(self, name: str, timeout: float = 10):
        import pywintypes
        import win32con
        import win32file
        self.file = win32file
        self.types = pywintypes
        self.handle = None
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.handle = win32file.CreateFile(name, win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                                                 0, None, win32con.OPEN_EXISTING,
                                                 win32con.FILE_FLAG_OVERLAPPED, None)
                break
            except pywintypes.error as exc:
                if exc.winerror not in (2, 231):
                    raise
                time.sleep(0.025)
        if self.handle is None:
            raise TimeoutError("native pipe did not become available")

    def _io(self, size_or_data: int | bytes, timeout: float = 3) -> bytes | int:
        import win32event
        ov = self.types.OVERLAPPED()
        ov.hEvent = win32event.CreateEvent(None, True, False, None)
        pending = False
        try:
            if isinstance(size_or_data, int):
                # Keep the allocated buffer alive until completion, including cancellation.
                buf = self.file.AllocateReadBuffer(size_or_data)
                code, _ = self.file.ReadFile(self.handle, buf, ov)
            else:
                buf = size_or_data
                code, _ = self.file.WriteFile(self.handle, buf, ov)
            pending = code == 997
            if code not in (0, 997):
                raise OSError(f"pipe operation failed: {code}")
            if pending and win32event.WaitForSingleObject(ov.hEvent, int(timeout * 1000)) != 0:
                raise TimeoutError("named pipe I/O deadline exceeded")
            n = self.file.GetOverlappedResult(self.handle, ov, True)
            pending = False
            return bytes(buf[:n]) if isinstance(size_or_data, int) else n
        finally:
            if pending:
                # This call issued the I/O on this same thread. pywin32 312 exposes
                # CancelIo (not CancelIoEx); no other operation is pending here.
                self.file.CancelIo(self.handle)
                try:
                    self.file.GetOverlappedResult(self.handle, ov, True)
                except self.types.error as exc:
                    if exc.winerror != 995:
                        raise
            ov.hEvent.Close()

    def receive(self) -> Packet:
        return read_packet(lambda n: self._io(n))

    def send(self, packet: Packet) -> None:
        data = packet.encode()
        if self._io(data) != len(data):
            raise OSError("short pipe write")

    def close(self) -> None:
        if self.handle is not None:
            self.handle.Close()
            self.handle = None
