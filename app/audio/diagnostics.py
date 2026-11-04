from __future__ import annotations

import math
import numpy as np


class AudioDiagnostics:
    """Bounded one-second FFT windows and cumulative signal statistics."""
    def __init__(self):
        self.samples = self.nonzero = self.windows = 0
        self.energy = self.peak = 0.0
        self.target_power = self.other_power = 0.0
        self.worst_ratio_db: float | None = None
        self.last_peak_hz: int | None = None
        self.peak_hz_min: int | None = None
        self.peak_hz_max: int | None = None
        self.spectrum_power = 0.0
        self._pending = np.empty(0, np.float32)

    def update(self, samples: np.ndarray) -> None:
        self.samples += len(samples)
        self.energy += float(np.dot(samples.astype(np.float64), samples.astype(np.float64)))
        self.nonzero += int(np.count_nonzero(np.abs(samples) > 1e-6))
        self.peak = max(self.peak, float(np.max(np.abs(samples), initial=0)))
        self._pending = np.concatenate((self._pending, samples))
        while len(self._pending) >= 16000:
            block, self._pending = self._pending[:16000], self._pending[16000:]
            power = np.abs(np.fft.rfft(block * np.hanning(16000))) ** 2
            self.spectrum_power += float(power.sum())
            if float(power.max()) > 1e-2:
                self.last_peak_hz = int(np.argmax(power))
                self.peak_hz_min = self.last_peak_hz if self.peak_hz_min is None else min(self.peak_hz_min, self.last_peak_hz)
                self.peak_hz_max = self.last_peak_hz if self.peak_hz_max is None else max(self.peak_hz_max, self.last_peak_hz)
            target = float(power[997:1004].sum())
            other = float(power[437:444].sum())
            self.target_power += target
            self.other_power += other
            self.windows += 1
            # Only windows with a meaningful target tone define leakage.
            if target > 1e-2:
                ratio = 10 * math.log10(max(other, 1e-30) / target)
                self.worst_ratio_db = ratio if self.worst_ratio_db is None else max(self.worst_ratio_db, ratio)

    def summary(self) -> dict:
        return {"samples": self.samples, "audio_seconds": self.samples / 16000,
                "rms": math.sqrt(self.energy / max(1, self.samples)), "peak": self.peak,
                "nonzero_samples": self.nonzero, "spectrum_windows": self.windows,
                "power_1000hz": self.target_power, "power_440hz": self.other_power,
                "last_peak_hz": self.last_peak_hz, "peak_hz_min": self.peak_hz_min, "peak_hz_max": self.peak_hz_max,
                "target_band_fraction": self.target_power / max(self.spectrum_power, 1e-30),
                "leakage_db": (10 * math.log10(max(self.other_power, 1e-30) / self.target_power)
                               if self.target_power > 1e-2 else None),
                "worst_window_leakage_db": self.worst_ratio_db}

    def isolation_passes(self, limit_db: float = -50) -> bool:
        return self.isolation_status(limit_db) == "passed"

    def isolation_status(self, limit_db: float = -50) -> str:
        if (self.peak_hz_min is not None and self.peak_hz_max is not None and
                980 <= self.peak_hz_min <= self.peak_hz_max <= 1020 and
                (self.peak_hz_min < 997 or self.peak_hz_max > 1003)):
            return "inconclusive_target_frequency_outside_band"
        passes = (self.windows > 0 and self.target_power > 1e-2 and
                self.worst_ratio_db is not None and self.worst_ratio_db <= limit_db)
        return "passed" if passes else "failed_or_target_not_confirmed"
