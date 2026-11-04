"""Paired real GPU decodes on identical windows; offline quality, NOT live latency.

Development: replay the prior 900-second real-time job plan, including previews.
Holdout: subsequent publisher cues, new deterministic VAD/rolling-window plan.
References are used for scoring/cue boundaries only, never model input.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict, dataclass
import hashlib
import importlib.metadata
import json
from pathlib import Path
import queue
import statistics
import subprocess
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.asr.buffer import AudioRing
from app.asr.config import ASRConfig
from app.asr.course_terms import CourseTerms
from app.asr.decoding import decode, segment_words
from app.asr.evaluation import read_cues, score
from app.asr.scheduler import Scheduler
from app.asr.source import FileSource
from app.asr.stabilizer import TranscriptStabilizer, render_words
from app.asr.types import InputFrame, RATE
from app.asr.vad import SileroStream
from app.asr.worker import configure_gpu_runtime


@dataclass(frozen=True)
class Window:
    start: int
    end: int
    endpoint: bool


def replay_windows(path: Path, samples: int) -> list[Window]:
    rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
    summary = [r for r in rows if r['event'] == 'asr_summary']
    if not summary or not summary[-1]['complete'] or summary[-1]['samples'] != samples:
        raise ValueError('baseline must be complete and match the requested development duration')
    plan = [Window(r['start_sample'], r['end_sample'], r['endpoint'])
            for r in rows if r['event'] == 'asr_result']
    if (not plan or any(not 0 <= w.start < w.end <= samples for w in plan)
            or any(a.end > b.end for a, b in zip(plan, plan[1:]))):
        raise ValueError('invalid or out-of-order baseline windows')
    return plan


def read_audio(path: Path, seconds: int) -> np.ndarray:
    source = FileSource(path, seconds, False, 256, lambda *a, **k: None)
    parts = []
    source.start()
    try:
        while not source.done.is_set() or not source.queue.empty():
            if source.error:
                raise RuntimeError('file decode failed') from source.error
            try: parts.append(source.queue.get(timeout=.2).audio)
            except queue.Empty: pass
        if source.error: raise RuntimeError('file decode failed') from source.error
    finally:
        source.close()
    audio = np.concatenate(parts) if parts else np.empty(0, np.float32)
    if len(audio) != seconds * RATE:
        raise ValueError('media is shorter than the requested trial')
    return audio


def new_windows(audio: np.ndarray, start: int, end: int, config: ASRConfig) -> list[Window]:
    ring = AudioRing(config.buffer_seconds)
    vad = SileroStream(config)
    scheduler = Scheduler(config, ring, lambda *a, **k: None)
    plan = []
    def drain():
        while (job := scheduler.pop()) is not None:
            plan.append(Window(start+job.start, start+job.end, job.endpoint))
            scheduler.completed_end = max(scheduler.completed_end, job.end)
    for position in range(0, end-start, 320):
        chunk = audio[start+position:min(start+position+320,end)]
        ring.append(InputFrame(position,chunk,(position+len(chunk))*1_000_000_000//RATE))
        for event in vad.feed(chunk):
            if event.kind == 'start': scheduler.speech_start(event.sample)
            else: scheduler.speech_end(ring.end)
        scheduler.advance(ring.end)
        drain()
    scheduler.speech_end(ring.end)
    drain()
    return plan


def run_pairs(model, audio, plan, course, config, log, label):
    states = {arm: TranscriptStabilizer(config.timestamp_tolerance_seconds, config.stable_tail_seconds)
              for arm in ['off','on']}
    text = {arm: [] for arm in states}
    timings = {arm: [] for arm in states}
    retries = {arm: 0 for arm in states}
    heuristic = {arm: 0 for arm in states}
    for index, window in enumerate(plan):
        # Counterbalance first/second decoder order and reuse one loaded model.
        for arm in (['off','on'] if index % 2 == 0 else ['on','off']):
            started = time.perf_counter_ns()
            segments, _, retried, _ = decode(model,audio[window.start:window.end],config.language,
                                             hotwords=course.for_language(config.language) if arm=='on' else None)
            elapsed = (time.perf_counter_ns()-started)/1e9
            words = segment_words(segments,window.start,window.end)
            update = states[arm].update(words,window.end,window.endpoint,window.start)
            committed = update.expired + update.committed
            text[arm].extend(w.text for w in committed)
            heuristic[arm] += len(update.expired) + (len(update.committed) if update.reason!='local_agreement' else 0)
            timings[arm].append(elapsed)
            retries[arm] += int(retried)
            log.write(json.dumps({'event':'offline_paired_decode','section':label,'arm':arm,'index':index,
                **asdict(window),'decode_seconds':elapsed,'repetition_retry':retried,
                'committed':render_words(committed),'candidate':render_words(update.candidate)},ensure_ascii=False)+'\n')
        if (index+1)%50==0 or index+1==len(plan):
            log.flush()
            print(json.dumps({'section':label,'windows_done':index+1,'total':len(plan)}),flush=True)
    return {arm:{'hypothesis':' '.join(text[arm]),'heuristic_committed_words':heuristic[arm],
                 'repetition_retries':retries[arm],
                 'decode_seconds':{'count':len(timings[arm]),'p50':statistics.median(timings[arm]),
                                   'p95':float(np.percentile(timings[arm],95)),'sum':sum(timings[arm])}}
            for arm in states}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline-dir',type=Path,default=ROOT/'docs/evidence/m1-realtime-15min-v1')
    p.add_argument('--languages',nargs='+',choices=['de','en'],default=['de','en'])
    p.add_argument('--development-seconds',type=int,default=900)
    p.add_argument('--holdout-seconds',type=int,default=300)
    args = p.parse_args()
    if not 1 <= args.development_seconds <= 1800 or not 1 <= args.holdout_seconds <= 1800:
        p.error('trial sections must each be 1..1800 seconds')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True,exist_ok=False)
    configure_gpu_runtime()
    import ctranslate2
    from faster_whisper import WhisperModel
    if ctranslate2.get_cuda_device_count() < 1:
        raise RuntimeError('CUDA unavailable; no fallback')
    model = WhisperModel(ASRConfig().model,device='cuda',compute_type='float16',local_files_only=True,
                         cpu_threads=4,num_workers=1)
    decode(model,np.zeros(RATE,np.float32),'de')  # explicitly discarded warmup
    result = {'complete':False,'method':'paired identical windows, alternating decode order; offline quality only',
              'config':asdict(ASRConfig()),'python':sys.version,
              'packages':{k:importlib.metadata.version(k) for k in ['faster-whisper','ctranslate2','av','numpy','jiwer']},
              'source_sha256':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest()
                               for f in (ROOT/'app').rglob('*.py')},'courses':{}}
    try:
        with (args.output/'decodes.jsonl').open('x',encoding='utf-8') as log:
            for lang in args.languages:
                config = ASRConfig(language=lang)
                stem = 'de-open-source-firmware' if lang=='de' else 'en-linear-algebra'
                media = ROOT/'tests/fixtures/public-m1'/(stem+('.mp3' if lang=='de' else '.mp4'))
                ref = ROOT/'tests/fixtures/public-m1'/(stem+('.srt' if lang=='de' else '.vtt'))
                profile = ROOT/'config/courses'/('de-firmware.toml' if lang=='de' else 'en-linear-algebra.toml')
                course = CourseTerms.load(profile,lang)
                hint_tokens = course.validate_tokens(model)
                total = args.development_seconds+args.holdout_seconds
                audio = read_audio(media,total)
                dev = replay_windows(args.baseline_dir/(lang+'.jsonl'),args.development_seconds*RATE)
                cues = read_cues(ref,total)
                held = [c for c in cues if c.start>=args.development_seconds]
                if not held: raise ValueError('no holdout reference cues')
                hstart,hend = round(held[0].start*RATE),round(held[-1].end*RATE)
                holdout = new_windows(audio,hstart,hend,config)
                if not holdout: raise ValueError('no holdout speech windows')
                (args.output/(lang+'-plan.json')).write_text(json.dumps({
                    'development':[asdict(w) for w in dev],'holdout':[asdict(w) for w in holdout]},indent=2),encoding='utf-8')
                terms = (['Firmware','Prozessor','Speicher','BIOS','UEFI','Intel','Kernel','Betriebssystem'] if lang=='de'
                         else ['matrix','matrices','vector','vectors','linear','equation','equations','column','row'])
                entry = {'course':course.metadata(hint_tokens),'hotwords':course.hotwords,
                         'media_sha256':hashlib.sha256(media.read_bytes()).hexdigest(),
                         'reference_sha256':hashlib.sha256(ref.read_bytes()).hexdigest(),'sections':{}}
                result['courses'][lang] = entry
                for label,plan,selected in [('development',dev,[c for c in cues if c.end<=args.development_seconds]),
                                             ('holdout',holdout,held)]:
                    arms = run_pairs(model,audio,plan,course,config,log,lang+'/'+label)
                    reference = ' '.join(c.text for c in selected)
                    for arm in arms.values():
                        hypothesis = arm.pop('hypothesis')
                        arm['score'] = score(reference,hypothesis,terms)
                        arm['prompted_terms_score'] = score(reference,hypothesis,list(course.terms))
                    entry['sections'][label] = {'window_count':len(plan),'audio_start_seconds':plan[0].start/RATE,
                        'audio_end_seconds':plan[-1].end/RATE,'reference_cues':len(selected),'arms':arms}
                    print(json.dumps({'finished':lang+'/'+label,'off_wer':arms['off']['score']['wer'],
                                      'on_wer':arms['on']['score']['wer']}),flush=True)
                    (args.output/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                del audio
        result['complete'] = True
    except BaseException as exc:
        result['error'] = {'type':type(exc).__name__,'message':str(exc)}
        raise
    finally:
        (args.output/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
