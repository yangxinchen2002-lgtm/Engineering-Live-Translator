"""One isolated CUDA worker, bounded jobs, optional text-only API and SAPI."""
from __future__ import annotations
from app.i18n import tr as _tr

import asyncio
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import queue
import time

from .media import Source, decode_window, probe
from .timeline import Cue
from .sentences import MAX_DECODE_SPAN, RIGHT_CONTEXT, plan_sentences

ROOT = Path(__file__).resolve().parents[2]


async def translate_cues(cues, language, options, context, ledger, stale, on_result=None):
    from app.translation.config import TranslationConfig
    from app.translation.credentials import read_credential
    from app.translation.factory import create_client
    from app.translation.glossary import Glossary
    from app.translation.prompt import prepare_messages
    from app.translation.providers import provider_info
    provider = options['provider']
    config = replace(TranslationConfig(), provider=provider, base_url=provider_info(provider).base_url,
                     model=options['model'], concurrency=1, max_retries=0,target_language=options.get('target_language','zh'))
    if options.get('glossary'):config=replace(config,glossary=options['glossary'])
    config=config.validate()
    credential = read_credential(provider)
    if credential is None:
        missing=[replace(c, translation_error=_tr('未找到该服务已保存的密钥；继续显示原文')) for c in cues]
        return [on_result(c) for c in missing] if on_result else missing
    glossary = Glossary.load(Path(config.glossary))
    client = create_client(config, credential)
    try:
        results = []
        for cue in cues:
            if stale():
                raise InterruptedError('generation changed')
            messages, _ = prepare_messages(cue.source, language, list(context), glossary, config)
            started = datetime.now(timezone.utc)
            usage, returned_model = None, ''
            async def request():
                nonlocal usage, returned_model
                text, done = '', False
                async for event in client.stream(messages):
                    if event.kind == 'delta':
                        text += event.text
                    elif event.kind == 'usage':
                        usage = event.usage
                    elif event.kind == 'done':
                        done = True
                        returned_model = event.model
                if not done or not text.strip():
                    raise ValueError('incomplete_translation')
                return text.strip()
            task = asyncio.create_task(request())
            try:
                deadline = time.monotonic() + 12
                while not task.done():
                    if stale():
                        raise InterruptedError('generation changed')
                    if time.monotonic() >= deadline:
                        raise TimeoutError('translation_deadline')
                    await asyncio.wait({task}, timeout=.1)
                translated = await task
                results.append(replace(cue, translation=translated))
                context.append(dict(source_text=cue.source, translated_text=translated))
            except InterruptedError:
                raise
            except Exception as e:
                code = getattr(e, 'code', type(e).__name__)
                results.append(replace(cue, translation_error=f"{_tr('翻译未完成（')}{code}{_tr('）；保留原文')}"))
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if returned_model and returned_model != config.model:
                    # Do not price an unrecognized returned model as the requested model.
                    ledger.card = None
                ledger.record(usage, started, datetime.now(timezone.utc))
            if on_result:results[-1]=on_result(results[-1])
        return results
    finally:
        await client.close()


def worker_main(source: Source, options: dict, tasks, output, current_generation, directory: str, playhead=None,narration=None,reading_commands=None):
    def send(kind, **data):
        output.put(dict(type=kind, **data), timeout=3)
    from app.asr.lease import ASRLease
    lease=ASRLease();speech=None;translation=None
    try:
        lease.acquire()
        import sys,faulthandler
        if sys.stderr is not None:faulthandler.enable()
        import av
        av.logging.set_level(av.logging.ERROR)  # open_media captures and sanitizes FFmpeg diagnostics.
        metadata = probe(source)
        if options.get('start_position', 0) >= metadata['duration']:
            raise ValueError(_tr('起播位置超过视频时长'))
        metadata['hls'] = source.hls
        send('metadata', **metadata)
        if options['narrate'] and options.get('speech_engine')=='qwen':
            from .tts import SpeechQueue
            speech=SpeechQueue(options,directory,current_generation,send,playhead,
                lambda:bool(narration.value) if narration is not None else options['narrate'])
        from app.asr.worker import configure_gpu_runtime
        from app.asr.config import ASRConfig
        asr_config=ASRConfig.load(ROOT/'config/asr.toml',language=options['language'],course_terms='')
        configure_gpu_runtime()
        from faster_whisper import WhisperModel
        import ctranslate2
        if asr_config.device=='cuda' and ctranslate2.get_cuda_device_count() < 1:
            raise RuntimeError('CUDA GPU unavailable; no fallback')
        loaded = time.monotonic()
        model = WhisperModel(asr_config.model, device=asr_config.device, compute_type=asr_config.compute_type,
                             local_files_only=True, cpu_threads=4, num_workers=1)
        from app.translation.usage import UsageLedger
        ledger = UsageLedger(options['model'], provider=options['provider'])
        if options['translate']:
            from .translation import CueTranslator
            translation=CueTranslator(options,current_generation,send,directory,speech,playhead,narration,reading_commands,own_speech=True)
            speech=None  # The translator now owns the speech lifetime, including model switches.
        usage=lambda:translation.snapshot() if translation else ledger.snapshot()
        send('ready', model_load_seconds=time.monotonic() - loaded, device=asr_config.device, compute_type=asr_config.compute_type)
        while True:
            task = tasks.get()
            if task is None:
                return
            generation, begin, end = task
            stale = lambda: generation != current_generation.value
            try:
                if stale():
                    raise InterruptedError('generation changed')
                started = time.monotonic()
                audio_start=max(0.,begin-1.)
                max_end=min(metadata['duration'],begin+MAX_DECODE_SPAN)
                decode_end=min(max_end,end+RIGHT_CONTEXT)
                passes=0
                while True:
                    send('decoding',generation=generation,begin=begin,end=decode_end)
                    audio,metrics=decode_window(source,audio_start,decode_end,stale)
                    segments,info=model.transcribe(audio,language=None if options['language']=='auto' else options['language'],
                        beam_size=1,temperature=0.,word_timestamps=True,condition_on_previous_text=False,vad_filter=True)
                    segments=list(segments);passes+=1
                    if stale():raise InterruptedError('generation changed')
                    plan=plan_sentences(segments,begin,end,audio_start,decode_end,metadata['duration'],generation,
                                        allow_fallback=decode_end>=max_end-.025)
                    send('preview',generation=generation,begin=begin,end=decode_end,
                         cues=[asdict(replace(c,source_language=info.language)) for c in plan.preview])
                    if not plan.needs_context:break
                    decode_end=max_end
                cues=[replace(c,source_language=info.language,asr_confirmed=True) for c in plan.cues]
                end=plan.end
                if len(cues)>96:raise ValueError(_tr('识别句段超过实验容量，未提交不完整结果'))
                asr_seconds = time.monotonic() - started
                send('preview',generation=generation,begin=begin,end=end,cues=[asdict(c) for c in cues])
                if stale():
                    raise InterruptedError('generation changed')
                # Commit source coverage immediately. Network/speech never hold
                # up the next ASR window, even for the first sentence in a batch.
                send('batch', generation=generation, begin=begin, end=end, cues=[asdict(c) for c in cues],
                     language=info.language, audio=metrics, asr_seconds=asr_seconds,
                     decoded_until=decode_end,sentence_context_passes=passes,
                     sentence_boundaries={reason:sum(c.boundary==reason for c in cues) for reason in {c.boundary for c in cues}},
                     source_preparation_seconds=time.monotonic() - started, usage=usage())
                if translation:
                    for cue in cues:translation.offer(generation,cue,info.language)
            except InterruptedError:
                send('cancelled', generation=generation,usage=usage())
    except BaseException as error:
        # Decoder/provider errors can contain signed URLs: never expose arbitrary exception text.
        message = str(error) if type(error) is ValueError else type(error).__name__
        try:
            send('error', message=message)
        except queue.Full:
            pass  # Parent also observes the failed process; never reports success.
        raise SystemExit(1)
    finally:
        try:
            try:
                if translation:translation.close()
            finally:
                if speech:speech.close()
        finally:lease.close()
