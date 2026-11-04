from __future__ import annotations
import asyncio
from collections import deque
from dataclasses import asdict
import json
import queue
import subprocess
import time
import uuid
import numpy as np
from .buffer import AudioRing
from .config import ASRConfig
from .language import LanguagePolicy
from .scheduler import Scheduler
from .source import AudioSource
from .stabilizer import TranscriptStabilizer, render_words
from .types import ASRResult, RATE
from .vad import SileroStream
from .worker import ASRWorker
from .clock import now_ns, metadata as clock_metadata, latency_seconds, sample_time


async def gpu_monitor(interval, emit, stop, samples):
    while not stop.is_set():
        try:
            result = await asyncio.to_thread(subprocess.run,
                ["nvidia-smi", "--query-gpu=memory.used,utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode == 0:
                parts = result.stdout.strip().splitlines()[0].split(",")
                used, utilization = int(parts[0].strip()), int(parts[1].strip())
                samples.append(used)
                emit("gpu", total_device_memory_mib=used, utilization_percent=utilization,
                     note="whole device including other apps; not model-only memory")
            else:
                emit("gpu_metrics_unavailable", reason=result.stderr.strip())
        except (OSError, ValueError, subprocess.TimeoutExpired, IndexError) as exc:
            emit("gpu_metrics_unavailable", reason=str(exc))
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            pass


async def run_pipeline(config: ASRConfig, source: AudioSource, emit, realtime: bool = True, *, session_id: str|None = None) -> dict:
    session_id = session_id or uuid.uuid4().hex
    emit("asr_session", session_id=session_id, config=asdict(config), realtime=realtime,
         clock=clock_metadata(), raw_audio_saved=False, text_saved_only_if_log_requested=True)
    worker = ASRWorker(config)
    emit("asr_worker_started", pid=worker.process.pid, parent_kill_closes_worker=True)
    ring = AudioRing(config.buffer_seconds)
    # Preserve clocks for candidates that leave the PCM window before they are
    # emitted as explicit boundary commits. PCM and clock history are separate.
    clock_capacity = int((config.buffer_seconds + config.window_seconds * (config.final_queue_capacity + 2)
                          + config.inference_timeout_seconds + 1) * RATE / 320) + 64
    clock_history = deque(maxlen=clock_capacity)
    scheduler = Scheduler(config, ring, emit)
    stabilizer = TranscriptStabilizer(config.timestamp_tolerance_seconds, config.stable_tail_seconds)
    language = LanguagePolicy(config)
    clock_started = time.monotonic()
    source_started = finished_input = False
    source_ready_reported = False
    pause_boundaries = deque()
    complete = False
    jobs = words_committed = words_previewed = 0
    heuristic_commits = repetition_retries = course_terms_jobs = 0
    preview_latencies, stable_latencies, inference_times, gpu_samples = [], [], [], []
    first_preview_segments = set()
    last_stats = last_audio_wall = time.monotonic()
    stop_monitor = asyncio.Event()
    monitoring = asyncio.create_task(gpu_monitor(config.gpu_poll_seconds, emit, stop_monitor, gpu_samples))
    try:
        # Load VAD before audio capture. Its first-use/import cost must not stall capture.
        vad = SileroStream(config)
        def apply_pause_boundaries():
            transitions=getattr(source,'pause_events',None)
            if transitions is None:return
            while True:
                try:transition=transitions.get_nowait()
                except queue.Empty:break
                if len(pause_boundaries)>=8:raise BufferError('capture pause boundary backlog; session incomplete')
                pause_boundaries.append(transition)
            while pause_boundaries and pause_boundaries[0]['sample']<=ring.end:
                transition=pause_boundaries.popleft();sample=transition['sample']
                if sample!=ring.end:raise RuntimeError('missed capture pause boundary')
                if transition['paused']:
                    scheduler.speech_end(sample)
                    ring.discard_before(sample)
                    # The endpoint job owns its old clock spans. A new job's
                    # first sample at this same index belongs AFTER the wall
                    # clock gap, so do not retain the old boundary clock here.
                    ring.clocks.clear()
                vad.reset_at(sample)
                emit('audio_capture_paused' if transition['paused'] else 'audio_capture_resumed',
                     sample=sample,paused_audio_excluded=True)
        while True:
            now = time.monotonic()
            message = worker.poll()
            if message and message["type"] == "ready":
                emit("asr_model_ready", **{k: v for k, v in message.items() if k != "type"})
                source.start()
                source_started = True
                last_audio_wall = now
            elif message and message["type"] == "result":
                result: ASRResult = message["result"]
                job = worker.busy
                if job is None or result.id != job.id:
                    raise RuntimeError("ASR result does not match active job")
                worker.busy = None
                scheduler.completed_end = max(scheduler.completed_end, job.end)
                inference = (result.finished_ns - result.started_ns) / 1e9
                inference_times.append(inference)
                jobs += 1
                repetition_retries += int(result.repetition_retry)
                course_terms_jobs += int(result.course_terms_applied)
                if result.repetition_retry:
                    emit("asr_repetition_retry", job_id=job.id, initial_word_count=result.initial_word_count,
                         final_word_count=len(result.words), no_repeat_ngram_size=4, repetition_penalty=1.05)
                emit("asr_result", job_id=job.id, required=job.required, endpoint=job.endpoint,
                     start_sample=job.start, end_sample=job.end, inference_seconds=inference,
                     queue_wait_seconds=(result.started_ns - job.created_ns) / 1e9,
                     submitted_ns=job.submitted_ns, finished_ns=result.finished_ns,
                     language=result.language, language_score=result.language_probability, word_count=len(result.words),
                     course_terms_applied=result.course_terms_applied)
                if result.text and not result.words:
                    emit("asr_text_without_word_timestamps", job_id=job.id, text=result.text)
                if language.observe(result.language, result.language_probability, job.end):
                    emit("language_locked", language=language.locked, reason="consistent_spaced_detections")
                source_language = language.locked or result.language
                update = stabilizer.update(result.words, job.end, job.endpoint, job.start, language=source_language)
                displayed_ns = now_ns()
                def time_at(sample):
                    return job.time_at(sample) if job.start <= sample <= job.end else sample_time(clock_history,sample)
                for state, words, reason in (
                    ("committed", update.expired, "window_boundary_unconfirmed"),
                    ("stable" if update.reason == "local_agreement" else "committed", update.committed, update.reason),
                    ("candidate", update.candidate, "unconfirmed")):
                    if not words:
                        continue
                    end_sample = words[-1].end
                    # Job carries a clock anchor even after its audio is removed from the ring.
                    audio_end_ns = time_at(end_sample)
                    latency = latency_seconds(audio_end_ns, displayed_ns) if realtime else None
                    if state in ("stable", "committed"):
                        words_committed += len(words)
                        if state == "committed":
                            heuristic_commits += len(words)
                        if latency is not None and state == "stable":
                            stable_latencies.append(latency)
                    else:
                        words_previewed += len(words)
                    first_preview = job.segment_id not in first_preview_segments
                    if first_preview:
                        first_preview_segments.add(job.segment_id)
                        if latency is not None:
                            preview_latencies.append(latency)
                    emit("transcript", session_id=session_id, segment_id=job.segment_id, revision=update.revision,
                         state=state, stability_reason=reason,
                         source_language=source_language, text=render_words(words, source_language),
                         words=[asdict(w) for w in words], start_sample=words[0].start, end_sample=end_sample,
                         audio_end_ns=audio_end_ns, displayed_ns=displayed_ns, latency_seconds=latency,
                         first_preview_for_segment=first_preview,
                         audio_start_to_display_seconds=((displayed_ns - time_at(words[0].start)) / 1e9 if realtime else None))
                def source_words(words):
                    return [{**asdict(w),'start_ns':time_at(w.start),'end_ns':time_at(w.end)} for w in words]
                emit('asr_update',session_id=session_id,segment_id=job.segment_id,job_id=job.id,
                     revision=update.revision,source_language=language.locked or result.language,
                     confirmed_words=source_words(update.expired+update.committed),
                     candidate_words=source_words(update.candidate),endpoint=job.endpoint,
                     stability_reason='contains_unconfirmed_boundary' if update.expired else update.reason)
            if not source_started:
                if now - clock_started > config.startup_timeout_seconds:
                    raise TimeoutError("ASR model initialization deadline exceeded")
            else:
                if source.error is not None:
                    raise RuntimeError(f"audio source failed: {source.error}") from source.error
                ready=getattr(source,'ready',None)
                if not source_ready_reported and ready is not None and ready.is_set():
                    emit('audio_source_ready',**source.ready_info)
                    source_ready_reported=True
                # Files in accelerated mode may pause decoding; live audio never waits for ASR.
                throttle = (not realtime and len(scheduler.required) >= config.final_queue_capacity - 1)
                if not finished_input and not throttle:
                    for _ in range(20):
                        try:
                            frame = source.queue.get_nowait()
                        except queue.Empty:
                            break
                        apply_pause_boundaries()
                        ring.append(frame)
                        clock_history.append((frame.start,frame.end,frame.end_ns))
                        last_audio_wall = now
                        for event in vad.feed(frame.audio):
                            emit("vad", state=event.kind, sample=event.sample)
                            if event.kind == "start":
                                scheduler.speech_start(event.sample)
                            else:
                                scheduler.speech_end(ring.end)  # include endpoint silence/context
                        scheduler.advance(ring.end)
                        if not realtime and len(scheduler.required) >= config.final_queue_capacity - 1:
                            break
                apply_pause_boundaries()
                if not finished_input and source.done.is_set() and source.queue.empty():
                    if source.error is not None:
                        raise RuntimeError(f"audio source failed: {source.error}") from source.error
                    scheduler.speech_end(ring.end)
                    finished_input = True
                    emit("audio_input_finished", samples=ring.end, audio_seconds=ring.end / RATE,
                         receiver_queue_high_water=source.high_water)
                if realtime and not finished_input and scheduler.start is not None and now - last_audio_wall > config.silence_seconds:
                    scheduler.speech_end(ring.end)
                    vad.state.reset()
                    emit("vad_idle_endpoint", sample=ring.end)
            if worker.busy and (now_ns() - worker.busy.submitted_ns) / 1e9 > config.inference_timeout_seconds:
                emit("asr_timeout", job_id=worker.busy.id, **scheduler.statistics())
                raise TimeoutError("ASR inference exceeded deadline; transcription incomplete")
            if worker.ready and worker.busy is None:
                job = scheduler.pop()
                if job:
                    job.language = language.locked
                    worker.submit(job)
                    emit('asr_submitted',job_id=job.id,start_sample=job.start,end_sample=job.end,
                         worker_pid=worker.process.pid,submitted_ns=job.submitted_ns)
            if finished_input and worker.busy is None and not scheduler.required and scheduler.preview is None:
                complete = True
                break
            if now - last_stats >= 1:
                emit("asr_queues", **scheduler.statistics(), audio_queue=source.queue.qsize(),
                     worker_busy=worker.busy is not None, ring_samples=len(ring.data))
                last_stats = now
            await asyncio.sleep(0.005)
    finally:
        stop_monitor.set()
        try:
            await monitoring
        finally:
            try:
                source.close()
            finally:
                worker.close()
        def distribution(values):
            return {"count": len(values), "p50": float(np.percentile(values, 50)) if values else None,
                    "p95": float(np.percentile(values, 95)) if values else None}
        summary = {"complete": complete, "samples": ring.end, "audio_seconds": ring.end / RATE,
                   "inference_jobs": jobs, "stable_word_count": words_committed - heuristic_commits,
                   "committed_word_count": words_committed, "heuristic_committed_words": heuristic_commits,
                   "pathological_repetition_retries": repetition_retries,
                   "course_terms_jobs": course_terms_jobs,
                   "preview_word_observations": words_previewed, "locked_language": language.locked,
                   "preview_latency_seconds": distribution(preview_latencies),
                   "stable_commit_latency_seconds": distribution(stable_latencies),
                   "inference_seconds": distribution(inference_times),
                   "gpu_total_peak_mib": max(gpu_samples) if gpu_samples else None,
                   "preview_windows_skipped": scheduler.skipped,
                   "elapsed_seconds": time.monotonic() - clock_started,
                   "latency_basis": "recognized phrase end; not human reference aligned" if realtime else "accelerated file: no live latency claims"}
        emit("asr_summary", **summary)
    return summary
