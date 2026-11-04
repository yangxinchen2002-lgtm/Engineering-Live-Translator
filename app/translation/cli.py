from __future__ import annotations
import asyncio
from dataclasses import replace
from pathlib import Path
import sys
from app.asr.clock import now_ns
from app.asr.config import ASRConfig
from app.asr.source import FileSource,LiveSource
from app.audio.processes import ProcessSelector,select_process
from .client import DeepSeekClient
from .client import ProviderError
from .config import TranslationConfig
from .credentials import read_credential
from .providers import provider_info
from .factory import create_client
from .runtime import run_bilingual,run_text


def translate(args) -> int:
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    from app.main import Reporter
    report=Reporter(args.log,clock=now_ns)
    latest={}
    def emit(event,**data):
        if event=='bilingual_summary':latest.update(data)
        report.emit(event,**data)
    async def run():
        config=TranslationConfig.load(args.translation_config)
        if getattr(args,'target_language',None) is not None:config=replace(config,target_language=args.target_language).validate()
        selected=getattr(args,'translation_provider',None)
        if selected is not None and selected!=config.provider:
            info=provider_info(selected);config=replace(config,provider=selected,base_url=info.base_url,model=info.models[0]).validate()
        if getattr(args,'translation_model',None) is not None:
            config=replace(config,model=args.translation_model).validate()
        if getattr(args,'translation_mode',None) is not None:
            config=replace(config,mode=args.translation_mode).validate()
        if getattr(args,'glossary',None) is not None:
            config=replace(config,glossary=str(args.glossary.resolve())).validate()
        source_only=getattr(args,'source_only',False)
        credential=None if source_only else (read_credential() if config.provider=='deepseek' else read_credential(config.provider))
        emit('translation_credentials',available=credential is not None,
             source=credential.source if credential else ('disabled_by_user' if source_only else 'unavailable'),
             provider=config.provider,model=config.model,secret_logged=False)
        client=(DeepSeekClient(config,credential) if config.provider=='deepseek' else create_client(config,credential)) if credential else None
        try:
            if args.command=='translate-text':
                await run_text(args.text,args.language,config,emit,client=client,history_path=args.history)
            else:
                asr=ASRConfig.load(args.config,model=args.model,language=args.language,device=args.device,
                                   compute_type=args.compute_type,course_terms='')
                live=args.command=='translate-live'
                if live:
                    processes,errors=ProcessSelector().discover(args.source)
                    for error in errors:emit('discovery_error',**error)
                    target=select_process(processes,args.pid)
                    if getattr(args,'expected_created',None) is not None and target.created!=args.expected_created:
                        raise ValueError('selected audio source process changed; refresh and select again')
                    emit('capture_target',pid=target.pid,created=target.created,path=target.path,
                         source=args.source,scope='process_tree')
                    source=LiveSource(args.helper,target,args.seconds,asr.audio_queue_capacity,emit,
                                      pause_event=getattr(args,'pause_event',None))
                else:source=FileSource(args.input,args.seconds,args.realtime,asr.audio_queue_capacity,emit)
                await run_bilingual(asr,config,source,emit,client=client,realtime=live or args.realtime,history_path=args.history,
                                    disabled_reason='translation_disabled_by_user' if source_only else 'missing_api_key',
                                    transcript_directory=getattr(args,'transcript_directory',None))
        finally:
            if client:await client.close()
    try:
        asyncio.run(run())
        if args.command!='translate-text' and not latest.get('asr_complete'):return 3
        return 0 if latest.get('translation_complete') and latest.get('final_subtitles',0)>0 and latest.get('history_complete',True) and latest.get('transcript_complete',True) else 3
    except KeyboardInterrupt:
        emit('bilingual_cancelled',complete=False);return 130
    except Exception as error:
        # Never include raw provider exceptions/headers/bodies or credential data.
        emit('bilingual_error',exception_type=type(error).__name__,
             message=('requested output already exists; refusing overwrite' if isinstance(error,FileExistsError) else
                      str(error) if isinstance(error,(ValueError,ProviderError)) else 'see source/translation diagnostic events'),
             complete=False);return 1
    finally:report.close()
