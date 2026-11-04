"""Real Win32 IPC checks, NOT evidence of native/VLC audio capture."""
import os
import threading
import uuid
import pytest

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Win32 named pipe required")


@pytest.mark.parametrize("timeout", [False, True])
def test_actual_pipe_fragmentation_and_cancellation(timeout):
    import win32file
    import win32pipe
    from app.audio.transport import NamedPipe
    from app.audio.protocol import Kind, control, read_packet
    name = rf"\\.\pipe\ELT-test-{uuid.uuid4().hex}"
    server = win32pipe.CreateNamedPipe(name, 3, 0, 1, 65536, 65536, 0, None)
    release = threading.Event()
    errors = []
    def serve():
        try:
            win32pipe.ConnectNamedPipe(server, None)
            packet = read_packet(lambda n: win32file.ReadFile(server, n)[1])
            assert packet.kind == Kind.START
            if timeout:
                release.wait(5)
            else:
                payload = control(Kind.STATUS, 0, state="test_peer").encode()
                for b in payload:
                    win32file.WriteFile(server, bytes([b]))
                release.wait(5)
        except BaseException as exc:
            errors.append(exc)
        finally:
            server.Close()
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    pipe = NamedPipe(name, timeout=2)
    try:
        pipe.send(control(Kind.START, 0))
        if timeout:
            with pytest.raises(TimeoutError):
                pipe._io(4, timeout=0.05)
        else:
            assert pipe.receive().json() == {"state": "test_peer"}
    finally:
        release.set()
        pipe.close()
        thread.join(5)
    assert not thread.is_alive()
    assert not errors
