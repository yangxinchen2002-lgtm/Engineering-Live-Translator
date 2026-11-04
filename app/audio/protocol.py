"""ELT/1: little-endian, length-prefixed packets. See docs/PROTOCOL.md."""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import json
import struct
from typing import Callable

VERSION = 1
MAX_BODY = 1024 * 1024
HEADER = struct.Struct("<HHQIHHIQQIHHI")
LENGTH = struct.Struct("<I")


class Kind(IntEnum):
    AUDIO = 1
    START = 2
    STOP = 3
    STATUS = 4
    ERROR = 5


class SampleFormat(IntEnum):
    NONE = 0
    S16 = 1
    S24 = 2
    S32 = 3
    F32 = 4


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Packet:
    kind: Kind
    sequence: int = 0
    rate: int = 0
    channels: int = 0
    format: SampleFormat = SampleFormat.NONE
    frames: int = 0  # per-channel sample count
    timestamp: int = 0  # WASAPI QPC in 100 ns units
    first_sample: int = 0  # cumulative input sample frames
    flags: int = 0  # native AUDCLNT_BUFFERFLAGS
    valid_bits: int = 0
    channel_mask: int = 0
    payload: bytes = b""

    def validate(self) -> None:
        if self.kind == Kind.AUDIO:
            widths = {SampleFormat.S16: 2, SampleFormat.S24: 3,
                      SampleFormat.S32: 4, SampleFormat.F32: 4}
            if self.format not in widths or not 8000 <= self.rate <= 384000:
                raise ProtocolError("unsupported PCM format/rate")
            if not 1 <= self.channels <= 32 or self.frames == 0:
                raise ProtocolError("invalid channels/frame count")
            bits = widths[self.format] * 8
            if not 1 <= self.valid_bits <= bits or (self.format == SampleFormat.F32 and self.valid_bits != 32):
                raise ProtocolError("invalid valid_bits")
            if len(self.payload) != self.frames * self.channels * widths[self.format]:
                raise ProtocolError("PCM size mismatch")
        else:
            if any((self.rate, self.channels, self.format, self.frames, self.timestamp,
                    self.first_sample, self.flags, self.valid_bits, self.channel_mask)):
                raise ProtocolError("control fields must be zero")
            self.json()

    def json(self) -> dict:
        try:
            value = json.loads(self.payload.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ProtocolError("invalid UTF-8 JSON control body") from exc
        if not isinstance(value, dict):
            raise ProtocolError("control body must be an object")
        return value

    def encode(self) -> bytes:
        self.validate()
        body = HEADER.pack(VERSION, self.kind, self.sequence, self.rate, self.channels,
                           self.format, self.frames, self.timestamp, self.first_sample,
                           self.flags, self.valid_bits, 0, self.channel_mask) + self.payload
        if len(body) > MAX_BODY:
            raise ProtocolError("packet too large")
        return LENGTH.pack(len(body)) + body

    @classmethod
    def decode(cls, body: bytes) -> Packet:
        if not HEADER.size <= len(body) <= MAX_BODY:
            raise ProtocolError("invalid packet size")
        v, k, seq, rate, ch, fmt, n, ts, first, flags, bits, reserved, mask = HEADER.unpack_from(body)
        if v != VERSION or reserved:
            raise ProtocolError("unsupported version/reserved field")
        try:
            p = cls(Kind(k), seq, rate, ch, SampleFormat(fmt), n, ts, first,
                    flags, bits, mask, body[HEADER.size:])
        except ValueError as exc:
            raise ProtocolError("unknown message/format") from exc
        p.validate()
        return p


def control(kind: Kind, sequence: int, **fields: object) -> Packet:
    return Packet(kind, sequence=sequence, payload=json.dumps(fields, ensure_ascii=False).encode("utf-8"))


def read_packet(read: Callable[[int], bytes]) -> Packet:
    def exact(n: int) -> bytes:
        parts = bytearray()
        while len(parts) < n:
            data = read(n - len(parts))
            if not data:
                raise EOFError("pipe closed mid-packet" if parts else "pipe closed")
            parts.extend(data)
        return bytes(parts)
    size, = LENGTH.unpack(exact(4))
    if not HEADER.size <= size <= MAX_BODY:
        raise ProtocolError(f"invalid body length: {size}")
    return Packet.decode(exact(size))

