from __future__ import annotations

from dataclasses import dataclass
from math import gcd
import numpy as np
from scipy.signal import firwin, upfirdn

from .protocol import Packet, ProtocolError, SampleFormat


def to_mono(packet: Packet) -> np.ndarray:
    """Decode little-endian PCM; arithmetic mean of all channels, including LFE.

    Integer valid bits are left aligned as specified by WAVEFORMATEXTENSIBLE.
    Silence packets still have explicit zero payload on the wire.
    """
    packet.validate()
    fmt = packet.format
    if fmt == SampleFormat.F32:
        data = np.frombuffer(packet.payload, dtype="<f4").astype(np.float32)
        if not np.isfinite(data).all():
            raise ProtocolError("non-finite float PCM")
    elif fmt == SampleFormat.S24:
        b = np.frombuffer(packet.payload, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | b[:, 1] << 8 | b[:, 2] << 16
        v = (v ^ 0x800000) - 0x800000
        data = (v.astype(np.float64) / 8388608).astype(np.float32)
    else:
        dtype, scale = {SampleFormat.S16: ("<i2", 32768), SampleFormat.S32: ("<i4", 2147483648)}[fmt]
        data = (np.frombuffer(packet.payload, dtype=dtype).astype(np.float64) / scale).astype(np.float32)
    return data.reshape(-1, packet.channels).mean(axis=1, dtype=np.float32)


class StreamingResampler:
    """Causal polyphase FIR with bounded history and decimation phase continuity.

    No per-packet zero padding. Output count is ceil(input_count * up / down).
    FIR group delay is exposed in output samples; no synthetic tail is emitted.
    """
    def __init__(self, source_rate: int, target_rate: int = 16000):
        if not 8000 <= source_rate <= 384000 or target_rate != 16000:
            raise ValueError("unsupported sample rate")
        divisor = gcd(source_rate, target_rate)
        self.up, self.down = target_rate // divisor, source_rate // divisor
        max_rate = max(self.up, self.down)
        self.taps = (firwin(20 * max_rate + 1, 1 / max_rate, window=("kaiser", 5.0)) * self.up
                     if max_rate > 1 else np.ones(1))
        self.delay_samples = (len(self.taps) - 1) / (2 * self.down)
        self._history = np.empty(0, np.float32)
        self._start = self._count = self._next = 0

    def process(self, mono: np.ndarray) -> np.ndarray:
        if mono.ndim != 1 or not np.isfinite(mono).all():
            raise ValueError("expected finite mono samples")
        if not mono.size:
            return np.empty(0, np.float32)
        data = np.concatenate((self._history, mono))
        self._count += len(mono)
        end = (self._count * self.up + self.down - 1) // self.down
        base = self._start * self.up // self.down  # history start is a multiple of down
        filtered = upfirdn(self.taps, data, up=self.up, down=self.down)
        out = filtered[self._next - base:end - base].astype(np.float32)
        self._next = end
        keep = (len(self.taps) + self.up - 1) // self.up
        trim = max(0, (len(data) - keep) // self.down * self.down)
        self._history = data[trim:].copy()
        self._start += trim
        return out


@dataclass(frozen=True)
class AudioFrame:
    start_sample: int
    samples: np.ndarray


class AudioProcessor:
    """One format/session, 320-sample output frames plus explicit final short frame."""
    def __init__(self):
        self._signature: tuple | None = None
        self.resampler: StreamingResampler | None = None
        self._pending = np.empty(0, np.float32)
        self.input_samples = self.output_samples = 0
        self._last_timestamp: int | None = None

    def process(self, packet: Packet) -> list[AudioFrame]:
        signature = (packet.rate, packet.channels, packet.format, packet.valid_bits, packet.channel_mask)
        if packet.first_sample != self.input_samples:
            raise ProtocolError("input sample gap/overlap; audio incomplete")
        if packet.flags & 1 and self.input_samples:
            raise ProtocolError("WASAPI data discontinuity; audio incomplete")
        if packet.flags & 4:
            raise ProtocolError("WASAPI timestamp error")
        if self._last_timestamp is not None and packet.timestamp < self._last_timestamp:
            raise ProtocolError("capture timestamp moved backwards")
        self._last_timestamp = packet.timestamp
        if self._signature is None:
            self._signature = signature
            self.resampler = StreamingResampler(packet.rate)
        elif signature != self._signature:
            raise ProtocolError("stream format changed; restart capture")
        assert self.resampler is not None
        normalized = self.resampler.process(to_mono(packet))
        self.input_samples += packet.frames
        self._pending = np.concatenate((self._pending, normalized))
        result = []
        while len(self._pending) >= 320:
            result.append(AudioFrame(self.output_samples, self._pending[:320].copy()))
            self.output_samples += 320
            self._pending = self._pending[320:]
        return result

    def finish(self) -> list[AudioFrame]:
        if not len(self._pending):
            return []
        frame = AudioFrame(self.output_samples, self._pending.copy())
        self.output_samples += len(self._pending)
        self._pending = np.empty(0, np.float32)
        return [frame]
