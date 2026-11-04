from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .config import ASRConfig
from .types import RATE


@dataclass(frozen=True)
class SpeechEvent:
    kind: str
    sample: int


class VadState:
    """Hysteresis and minimum speech/silence durations, independent of the model."""
    def __init__(self, config: ASRConfig):
        self.config = config
        self.active = False
        self.candidate: int | None = None
        self.silence: int | None = None

    def update(self, probability: float, start: int, count: int = 512) -> list[SpeechEvent]:
        if not np.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("invalid VAD probability")
        if probability >= self.config.vad_threshold:
            self.silence = None
            if not self.active:
                if self.candidate is None:
                    self.candidate = start
                if start + count - self.candidate >= int(self.config.min_speech_seconds * RATE):
                    self.active = True
                    return [SpeechEvent("start", max(0, self.candidate - int(self.config.pre_roll_seconds * RATE)))]
        elif probability < self.config.vad_negative_threshold:
            self.candidate = None
            if self.active:
                if self.silence is None:
                    self.silence = start
                if start + count - self.silence >= int(self.config.silence_seconds * RATE):
                    self.active = False
                    end = self.silence
                    self.silence = None
                    return [SpeechEvent("end", end)]
        return []

    def reset(self) -> None:
        self.active = False
        self.candidate = self.silence = None


class SileroStream:
    """Silero v6 ONNX bundled with faster-whisper 1.2.1; keep LSTM/context state.

    Uses 512 sample chunks + 64 sample context, CPU ONNX, no Torch dependency.
    The ONNX input/output names and shapes are checked at construction.
    """
    def __init__(self, config: ASRConfig):
        import onnxruntime as ort
        from faster_whisper.utils import get_assets_path
        from pathlib import Path
        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(Path(get_assets_path()) / "silero_vad_v6.onnx"),
                                             providers=["CPUExecutionProvider"], sess_options=options)
        if [i.name for i in self.session.get_inputs()] != ["input", "h", "c"]:
            raise RuntimeError("unexpected Silero model schema; verify pinned dependency")
        self.h = np.zeros((1, 1, 128), np.float32)
        self.c = np.zeros_like(self.h)
        self.context = np.zeros(64, np.float32)
        self.pending = np.empty(0, np.float32)
        self.position = 0
        self.state = VadState(config)

    def reset_at(self,sample:int) -> None:
        """Break temporal context at a user pause without reloading ONNX."""
        self.h.fill(0);self.c.fill(0);self.context.fill(0)
        self.pending=np.empty(0,np.float32);self.position=sample;self.state.reset()

    def feed(self, audio: np.ndarray) -> list[SpeechEvent]:
        self.pending = np.concatenate((self.pending, audio))
        events = []
        while len(self.pending) >= 512:
            chunk = self.pending[:512]
            model_input = np.concatenate((self.context, chunk))[None, :]
            out, self.h, self.c = self.session.run(None, {"input": model_input, "h": self.h, "c": self.c})
            self.context = chunk[-64:].copy()
            probability = float(np.asarray(out).reshape(-1)[0])
            events.extend(self.state.update(probability, self.position))
            self.position += 512
            self.pending = self.pending[512:]
        return events
