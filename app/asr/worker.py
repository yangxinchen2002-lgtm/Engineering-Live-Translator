from __future__ import annotations
from dataclasses import asdict
import multiprocessing as mp
import os
from pathlib import Path
import queue
import time
import traceback
from .config import ASRConfig, ROOT
from .types import ASRJob, ASRResult, Word, RATE
from .decoding import decode, segment_words
from .course_terms import CourseTerms
from .clock import now_ns

_DLL_HANDLES = []


def configure_gpu_runtime() -> list[str]:
    paths = sorted({p.parent.resolve() for p in (ROOT / "tools/gpu-runtime").rglob("*.dll")})
    if os.name == "nt":
        for p in paths:
            _DLL_HANDLES.append(os.add_dll_directory(str(p)))
        if paths:
            os.environ["PATH"] = os.pathsep.join(map(str, paths)) + os.pathsep + os.environ.get("PATH", "")
    return list(map(str, paths))


def worker_main(config: ASRConfig, tasks, output) -> None:
    from .lease import ASRLease
    lease=ASRLease()
    try:
        lease.acquire()
        course = CourseTerms.load(Path(config.course_terms), config.language) if config.course_terms else None
        paths = configure_gpu_runtime()
        import ctranslate2
        from faster_whisper import WhisperModel
        if config.device == "cuda" and ctranslate2.get_cuda_device_count() < 1:
            raise RuntimeError("CUDA GPU unavailable; no CPU fallback was performed")
        start = now_ns()
        model = WhisperModel(config.model, device=config.device, compute_type=config.compute_type,
                             local_files_only=True, cpu_threads=4, num_workers=1)
        hint_tokens = course.validate_tokens(model) if course else 0
        load_seconds = (now_ns() - start) / 1e9
        import numpy as np
        warmup = now_ns()
        segments, _ = model.transcribe(np.zeros(RATE, np.float32),
                                       language=config.language if config.language != 'auto' else 'de', task="transcribe",
                                       beam_size=1, vad_filter=False, temperature=0.0)
        list(segments)  # discard explicitly synthetic warmup; never emit as a transcript
        output.put({"type": "ready", "model_load_seconds": load_seconds,
                    "warmup_seconds": (now_ns() - warmup) / 1e9,
                    "device": model.model.device, "compute_type": model.model.compute_type,
                    "model": config.model, "cuda_dll_paths": paths, "ctranslate2": ctranslate2.__version__,
                    "course_terms": course.metadata(hint_tokens) if course else None}, timeout=5)
        while True:
            job: ASRJob | None = tasks.get()
            if job is None:
                return
            started = now_ns()
            hotwords = course.for_language(job.language) if course else None
            segments, info, retried, initial_word_count = decode(model, job.audio, job.language, hotwords=hotwords)
            words = segment_words(segments, job.start, job.end, info.language)
            result = ASRResult(job.id, words, info.language, float(info.language_probability),
                               started, now_ns(), "".join(s.text for s in segments).strip(), retried,
                               initial_word_count, bool(hotwords))
            output.put({"type": "result", "result": result}, timeout=5)
    except BaseException as exc:
        try:
            output.put({"type": "error", "error": str(exc), "traceback": traceback.format_exc()}, timeout=2)
        except queue.Full:
            pass  # parent also detects the process exit; no false success
        raise SystemExit(1)
    finally:lease.close()


class ASRWorker:
    def __init__(self, config: ASRConfig):
        self.config = config
        context = mp.get_context("spawn")
        self.tasks = context.Queue(maxsize=1)
        self.output = context.Queue(maxsize=2)
        self.process = context.Process(target=worker_main, args=(config, self.tasks, self.output), name="ELT-ASR")
        self.owner_job = None
        if os.name == "nt":
            import win32job
            self.owner_job = win32job.CreateJobObject(None, "")
            info = win32job.QueryInformationJobObject(self.owner_job, win32job.JobObjectExtendedLimitInformation)
            info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(self.owner_job, win32job.JobObjectExtendedLimitInformation, info)
        try:
            self.process.start()
            if self.owner_job is not None:
                import win32api
                import win32job
                process_handle = win32api.OpenProcess(0x0100 | 0x0001, False, self.process.pid)
                try:
                    win32job.AssignProcessToJobObject(self.owner_job, process_handle)
                finally:
                    process_handle.Close()
        except BaseException:
            if self.process.pid and self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=5)
            if self.owner_job is not None:
                self.owner_job.Close()
            for q in (self.tasks, self.output):
                q.cancel_join_thread()
                q.close()
            raise
        self.busy: ASRJob | None = None
        self.ready = False

    def poll(self) -> dict | None:
        try:
            value = self.output.get_nowait()
        except queue.Empty:
            if self.process.exitcode is not None:
                raise RuntimeError(f"ASR worker exited unexpectedly: {self.process.exitcode}")
            return None
        if value["type"] == "error":
            raise RuntimeError(f"ASR worker error: {value['error']}\n{value['traceback']}")
        if value["type"] == "ready":
            self.ready = True
        return value

    def submit(self, job: ASRJob) -> None:
        if not self.ready or self.busy:
            raise RuntimeError("worker is not ready/idle")
        job.submitted_ns = now_ns()
        self.tasks.put_nowait(job)
        self.busy = job

    def close(self) -> None:
        if self.process.is_alive():
            try:
                self.tasks.put_nowait(None)
            except queue.Full:
                pass
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(timeout=5)
        else:
            self.process.join(timeout=1)
        if self.process.is_alive():
            self.process.kill()
            self.process.join(timeout=3)
        for q in (self.tasks, self.output):
            q.cancel_join_thread()
            q.close()
        self.process.close()
        if self.owner_job is not None:
            self.owner_job.Close()
            self.owner_job = None
