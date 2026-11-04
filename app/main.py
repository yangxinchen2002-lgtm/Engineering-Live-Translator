"""ELT CLI: explicit capture, local ASR and text translation. No GUI."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import wave
import numpy as np

from .audio.capture import CaptureSession
from .audio.diagnostics import AudioDiagnostics
from .audio.processes import ProcessSelector, identity_changes, select_process, SOURCE_EXECUTABLES
from .audio.processing import AudioProcessor
from .audio.protocol import Kind
from .languages import ASR_LANGUAGES, SOURCE_LANGUAGES

ROOT = Path(__file__).resolve().parents[1]


class Reporter:
    def __init__(self, path: Path | None, clock=None):
        self.file = path.open("x", encoding="utf-8") if path else None
        self.clock = clock or time.monotonic_ns

    def emit(self, event: str, **data: object) -> None:
        line = json.dumps({"event": event, "monotonic_ns": self.clock(), **data}, ensure_ascii=False)
        print(line, flush=True)
        if self.file:
            self.file.write(line + "\n")
            self.file.flush()

    def close(self) -> None:
        if self.file:
            self.file.close()


def capture_once(args: argparse.Namespace, report: Reporter, cycle: int) -> bool:
    found, errors = ProcessSelector().discover(args.source)
    for error in errors:
        report.emit("discovery_error", **error)
    target = select_process(found, args.pid)
    report.emit("selected", cycle=cycle, source=args.source, scope='process_tree', **asdict(target))
    processor, diagnostics = AudioProcessor(), AudioDiagnostics()
    wav = wav_file = None
    session = None
    complete = False
    started = time.monotonic()
    stopping_at: float | None = None
    last_report = started
    try:
        if args.wav:
            path = args.wav if args.cycles == 1 else args.wav.with_name(f"{args.wav.stem}-{cycle}{args.wav.suffix}")
            wav_file = path.open("xb")
            wav = wave.open(wav_file, "wb")
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            report.emit("debug_wav_enabled", path=str(path.resolve()), limit_seconds=args.wav_seconds,
                        note="16-bit debug export; internal audio is float32")
        def consume(frames: list) -> None:
            for frame in frames:
                diagnostics.update(frame.samples)
                if wav and frame.start_sample < args.wav_seconds * 16000:
                    remaining = int(args.wav_seconds * 16000) - frame.start_sample
                    data = np.clip(frame.samples[:remaining], -1, 32767 / 32768)
                    wav.writeframesraw((data * 32768).astype("<i2").tobytes())
        session = CaptureSession(args.helper, target)
        while True:
            try:
                now = time.monotonic()
                if now - started >= args.seconds and stopping_at is None:
                    session.stop()
                    stopping_at = now
                if stopping_at is not None and now - stopping_at > 8:
                    raise TimeoutError("STOP did not complete within 8 seconds")
                packet = session.receive()
                if packet.kind == Kind.AUDIO:
                    if packet.flags:
                        report.emit("audio_flags", flags=packet.flags, first_sample=packet.first_sample,
                                    capture_qpc_100ns=packet.timestamp)
                    consume(processor.process(packet))
                else:
                    info = packet.json()
                    report.emit("native_status" if packet.kind == Kind.STATUS else "native_error", **info)
                    if packet.kind == Kind.ERROR:
                        raise RuntimeError(f"native capture error: {info}")
                    if info.get("state") == "stopped":
                        if stopping_at is None:
                            raise RuntimeError("unsolicited native stop")
                        consume(processor.finish())
                        complete = True
                        break
                if now - last_report >= 1:
                    stats = diagnostics.summary()
                    report.emit("audio_diagnostics", **stats, input_samples=processor.input_samples,
                                signal="present" if stats["rms"] > args.signal_rms_min else "no_signal_above_threshold",
                                resampler_delay_samples=(processor.resampler.delay_samples if processor.resampler else None))
                    last_report = now
            except KeyboardInterrupt:
                if stopping_at is not None:
                    raise
                session.stop()
                stopping_at = time.monotonic()
                report.emit("stop_requested", reason="keyboard")
    finally:
        if wav:
            wav.close()
        if wav_file:
            wav_file.close()
        if session:
            session.close()
            if session.stderr:
                report.emit("native_stderr", text=session.stderr)
            if session.returncode != 0:
                complete = False
        stats = diagnostics.summary()
        signal = stats["rms"] > args.signal_rms_min and stats["nonzero_samples"] > 0
        isolation = diagnostics.isolation_passes(args.leakage_db) if args.isolation else None
        report.emit("capture_summary", cycle=cycle, complete=complete, signal_detected=signal,
                    isolation_pass=isolation, isolation_status=(diagnostics.isolation_status(args.leakage_db) if args.isolation else None),
                    leakage_limit_db=args.leakage_db,
                    signal_rms_min=args.signal_rms_min, wall_seconds=time.monotonic() - started, **stats)
    return complete and signal and (not args.isolation or bool(isolation))


def generate_tones(directory: Path, seconds: int) -> None:
    """Explicit fixtures only; never used as production capture input."""
    if not directory.is_dir():
        raise ValueError("create the specified fixture directory first")
    rate = 48000
    for frequency in (1000, 440):
        path = directory / f"tone-{frequency}hz.wav"
        block = (np.sin(2 * np.pi * frequency * np.arange(rate) / rate) * 8192).astype("<i2").tobytes()
        with path.open("xb") as output, wave.open(output, "wb") as wav:
            wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            for _ in range(seconds):
                wav.writeframesraw(block)
        print(json.dumps({"created": str(path.resolve()), "seconds": seconds}))


def positive(value: str) -> float:
    n = float(value)
    if not np.isfinite(n) or n <= 0:
        raise argparse.ArgumentTypeError("must be finite and positive")
    return n


def main(argv: list[str] | None = None, *, pause_event=None) -> int:
    arguments=sys.argv[1:] if argv is None else argv
    secret_flags={'--api-key','--key',*(f'--{name}-api-key' for name in ('deepseek','openai','anthropic','claude','gemini','google'))}
    if any(value.split('=',1)[0] in secret_flags for value in arguments):
        print(json.dumps({'error':'API keys must use the credential store or environment; never command-line arguments'}),file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description="ELT - per-app audio capture, local ASR and bilingual subtitles")
    sub = parser.add_subparsers(dest="command", required=True)
    key = sub.add_parser('deepseek-key', help='set/status/delete the named Windows user credential; no key argument')
    key.add_argument('action',choices=('set','status','delete'))
    from app.translation.providers import PROVIDERS
    keys=sub.add_parser('api-key',help='manage a selected provider credential with hidden local input')
    keys.add_argument('action',choices=('set','status','delete'));keys.add_argument('--provider',choices=tuple(PROVIDERS),default='deepseek')
    listing = sub.add_parser("list", help="list selected app identities; never captures audio")
    listing.add_argument('--source', choices=tuple(SOURCE_EXECUTABLES), default='vlc')
    listing.add_argument("--watch", type=positive, metavar="SECONDS", help="report identity changes at this interval")
    capture = sub.add_parser("capture", help="capture the selected app tree; no WAV/log files unless requested")
    capture.add_argument("--pid", type=int)
    capture.add_argument('--source', choices=tuple(SOURCE_EXECUTABLES), default='vlc')
    capture.add_argument("--helper", type=Path, default=ROOT / "native/build/Release/elt_capture.exe")
    capture.add_argument("--seconds", type=positive, default=30)
    capture.add_argument("--cycles", type=int, choices=range(1, 101), default=1)
    capture.add_argument("--log", type=Path, help="new JSONL file; refuses overwrite")
    capture.add_argument("--wav", type=Path, help="new short debug WAV at this explicit path")
    capture.add_argument("--wav-seconds", type=positive, default=10)
    capture.add_argument("--isolation", action="store_true", help="require 1000 Hz and reject 440 Hz leakage")
    capture.add_argument("--leakage-db", type=float, default=-50)
    capture.add_argument("--signal-rms-min", type=positive, default=1e-4,
                         help="minimum RMS for signal evidence; default -80 dBFS")
    tones = sub.add_parser("tones", help="write test WAV fixtures to an explicit existing directory")
    tones.add_argument("--directory", type=Path, required=True)
    tones.add_argument("--seconds", type=int, choices=range(1, 3601), default=600)
    for name in ("asr-live", "asr-file",'translate-live','translate-file'):
        bilingual=name.startswith('translate-')
        asr = sub.add_parser(name, help="M2 bilingual subtitles" if bilingual else "M1 local transcription; original text only")
        asr.add_argument("--config", type=Path, default=ROOT / "config/asr.toml")
        asr.add_argument("--language", choices=ASR_LANGUAGES)
        asr.add_argument("--model", help="explicit local converted model path")
        asr.add_argument("--device", choices=("cuda", "cpu"))
        asr.add_argument("--compute-type", choices=("float16", "int8_float16", "int8", "float32"))
        if not bilingual:
            course = asr.add_mutually_exclusive_group()
            course.add_argument('--course-terms', type=Path, help='explicit local course vocabulary TOML')
            course.add_argument('--no-course-terms', action='store_true', help='disable any configured course vocabulary')
        else:
            asr.add_argument('--translation-config',type=Path,default=ROOT/'config/translation.toml')
            asr.add_argument('--translation-provider',choices=tuple(PROVIDERS))
            asr.add_argument('--translation-model',help='explicit provider model ID; unrelated to the ASR model')
            asr.add_argument('--target-language',choices=('zh','en'))
            asr.add_argument('--translation-mode',choices=('preview','sentence'),
                             help='preview: translate stable prefixes; sentence: wait for source segment closure')
            asr.add_argument('--glossary',type=Path,help='explicit translation glossary; ASR course hints remain disabled')
            asr.add_argument('--history',type=Path,help='explicit new final-subtitle history; default off')
            asr.add_argument('--transcript-directory',type=Path,help='opt-in per-session bilingual TXT folder; default off')
            asr.add_argument('--source-only',action='store_true',help='local original text only; never construct an API client')
        asr.add_argument("--seconds", type=positive, default=60)
        asr.add_argument("--log", type=Path, help="explicit new diagnostic/transcript JSONL; no audio saved")
        if name.endswith('-live'):
            asr.add_argument('--source', choices=tuple(SOURCE_EXECUTABLES), default='vlc')
            asr.add_argument("--pid", type=int)
            asr.add_argument('--expected-created',type=int,help='reject a stale selected process identity')
            asr.add_argument("--helper", type=Path, default=ROOT / "native/build/Release/elt_capture.exe")
        else:
            asr.add_argument("--input", type=Path, required=True)
            asr.add_argument("--realtime", action="store_true",default=bilingual, help="pace file input for latency tests")
            if bilingual:asr.add_argument('--accelerated',dest='realtime',action='store_false',help='offline throughput only; no live latency claim')
    text=sub.add_parser('translate-text',help='translate explicit text; no audio capture or ASR')
    text.add_argument('--text',required=True)
    text.add_argument('--language',choices=SOURCE_LANGUAGES,required=True)
    text.add_argument('--translation-config',type=Path,default=ROOT/'config/translation.toml')
    text.add_argument('--translation-provider',choices=tuple(PROVIDERS))
    text.add_argument('--translation-model')
    text.add_argument('--target-language',choices=('zh','en'))
    text.add_argument('--translation-mode',choices=('preview','sentence'))
    text.add_argument('--glossary',type=Path,help='explicit translation glossary')
    text.add_argument('--history',type=Path)
    text.add_argument('--log',type=Path)
    args = parser.parse_args(argv)
    args.pause_event = pause_event
    report = None
    try:
        if args.command in ('deepseek-key','api-key'):
            from .translation.credentials import manage_credential
            print(json.dumps(manage_credential(args.action) if args.command=='deepseek-key' else
                             manage_credential(args.action,args.provider),ensure_ascii=False))
            return 0
        if args.command in ('translate-live','translate-file','translate-text'):
            from .translation.cli import translate
            return translate(args)
        if args.command in ("asr-live", "asr-file"):
            from .asr.cli import transcribe
            return transcribe(args)
        if args.command == "list":
            previous = []
            while True:
                found, errors = ProcessSelector().discover(args.source)
                print(json.dumps({"source":args.source,"scope":"process_tree","processes": [asdict(p) for p in found], "errors": errors,
                                  "changes": {k: [asdict(p) for p in v] for k, v in identity_changes(previous, found).items()}},
                                 ensure_ascii=False), flush=True)
                if not args.watch:
                    return 0
                previous = found
                time.sleep(args.watch)
        if args.command == "tones":
            generate_tones(args.directory, args.seconds)
            return 0
        if args.wav_seconds > 30:
            parser.error("--wav-seconds must be <= 30 (short debug exports only)")
        if not np.isfinite(args.leakage_db) or args.leakage_db >= 0:
            parser.error("--leakage-db must be a finite negative number")
        report = Reporter(args.log)
        for cycle in range(1, args.cycles + 1):
            if not capture_once(args, report, cycle):
                return 3  # incomplete, no signal, or failed isolation
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        if report:
            report.emit("error", type=type(exc).__name__, message=str(exc))
        else:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if report:
            report.close()


if __name__ == "__main__":
    raise SystemExit(main())
