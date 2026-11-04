from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from app.asr.pipeline import run_pipeline
from app.subtitles.coordinator import SubtitleCoordinator
from app.subtitles.history import HistoryWriter
from app.subtitles.transcript import TranscriptWriter
from .glossary import Glossary
from .worker import TranslationWorker


async def run_bilingual(asr_config,config,source,emit,*,client=None,realtime=True,history_path:Path|None=None,
                        disabled_reason='missing_api_key',transcript_directory:Path|None=None):
    # Explicit user decision: no ASR course prompting in the M2 pipeline.
    asr_config=replace(asr_config,course_terms=None)
    glossary=Glossary.load(Path(config.glossary))
    coordinator=SubtitleCoordinator(config,emit,realtime=realtime)
    history=HistoryWriter(history_path,config.history_queue_capacity,emit)
    transcript=TranscriptWriter(transcript_directory,coordinator.session_id,asr_config.language,emit,
                                capacity=config.history_queue_capacity,target_language=config.target_language)
    worker=TranslationWorker(config,client,glossary,coordinator,emit,disabled_reason=disabled_reason)
    coordinator.on_source_closed=transcript.offer
    def final(record):history.offer(record);transcript.offer(record)
    coordinator.on_final=final
    asr_complete=False
    def on_asr(event,**data):
        emit(event,**data)
        if event in ('audio_source_ready','asr_update'):transcript.source_started()
        if event in ('audio_capture_paused','audio_capture_resumed'):transcript.capture_pause(event=='audio_capture_paused')
        if event=='asr_update':coordinator.consume(**data)
    try:
        history.start();transcript.start();worker.start()
        asr_summary=await run_pipeline(asr_config,source,on_asr,realtime,session_id=coordinator.session_id)
        asr_complete=asr_summary['complete']
        coordinator.end_source()
        return asr_summary
    except Exception as error:
        # This is exclusively the local ASR/source path, not provider exceptions.
        emit('bilingual_source_error',exception_type=type(error).__name__,message=str(error),asr_complete=False)
        raise
    finally:
        stats={};history_stats={};transcript_stats={}
        transcript.source_ended()
        if coordinator.current is not None:transcript.offer(coordinator.records[coordinator.current])
        try:
            try:stats=await worker.close(drain=asr_complete)
            finally:
                try:history_stats=await history.close()
                finally:transcript_stats=await transcript.close(source_complete=asr_complete)
        finally:
            summary={**coordinator.summary(),**stats,**history_stats,**transcript_stats,'asr_complete':asr_complete,
                     'translation_available':worker.available,'asr_course_terms_enabled':False}
            summary['translation_complete']=asr_complete and summary['translation_complete']
            emit('bilingual_summary',**summary)


async def run_text(text,language,config,emit,*,client=None,history_path=None):
    glossary=Glossary.load(Path(config.glossary))
    coordinator=SubtitleCoordinator(config,emit,realtime=False)
    history=HistoryWriter(history_path,config.history_queue_capacity,emit)
    worker=TranslationWorker(config,client,glossary,coordinator,emit)
    coordinator.on_final=history.offer
    try:
        history.start();worker.start()
        coordinator.submit_text(text,language)
    finally:
        try:stats=await worker.close()
        finally:history_stats=await history.close()
    summary={**coordinator.summary(),**stats,**history_stats,'input_kind':'text',
             'translation_available':worker.available}
    emit('bilingual_summary',**summary)
    return summary
