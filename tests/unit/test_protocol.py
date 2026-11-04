import io
import json
import struct
import pytest
from app.audio.protocol import HEADER, MAX_BODY, Kind, Packet, ProtocolError, SampleFormat, control, read_packet


def test_golden_control_bytes():
    wire = control(Kind.START, 0).encode()
    assert HEADER.size == 52
    assert wire.hex() == "3600000001000200" + "00" * 48 + "7b7d"
    assert read_packet(io.BytesIO(wire).read).json() == {}


def test_fragmented_read():
    p = control(Kind.STATUS, 123, state="暂停")
    stream = io.BytesIO(p.encode())
    assert read_packet(lambda n: stream.read(min(n, 3))) == p


@pytest.mark.parametrize("size", [0, 51, MAX_BODY + 1, 0xFFFFFFFF])
def test_invalid_prefix(size):
    with pytest.raises(ProtocolError):
        read_packet(io.BytesIO(struct.pack("<I", size)).read)


@pytest.mark.parametrize("wire", [b"", b"\x01", control(Kind.STOP, 0).encode()[:-1]])
def test_truncated(wire):
    with pytest.raises(EOFError):
        read_packet(io.BytesIO(wire).read)


@pytest.mark.parametrize("offset,value", [(0, 2), (2, 99), (46, 1)])
def test_header_rejection(offset, value):
    body = bytearray(control(Kind.START, 0).encode()[4:])
    body[offset] = value
    with pytest.raises(ProtocolError):
        Packet.decode(body)


@pytest.mark.parametrize("payload", [b"no json", b"[]", b"\xff"])
def test_invalid_control(payload):
    with pytest.raises(ProtocolError):
        Packet(Kind.STATUS, payload=payload).encode()


def test_audio_validation():
    p = Packet(Kind.AUDIO, rate=48000, channels=2, format=SampleFormat.S16, frames=3,
               valid_bits=16, payload=b"\0" * 12)
    assert read_packet(io.BytesIO(p.encode()).read) == p
    with pytest.raises(ProtocolError):
        Packet(Kind.AUDIO, rate=48000, channels=2, format=SampleFormat.S16,
               frames=3, valid_bits=16, payload=b"\0").encode()


def test_control_fields_zero():
    with pytest.raises(ProtocolError):
        Packet(Kind.STATUS, rate=16000, payload=json.dumps({}).encode()).encode()
