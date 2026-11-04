import asyncio
import sys
from .config import ASRConfig
from .pipeline import run_pipeline
from .source import FileSource, LiveSource
from app.audio.processes import ProcessSelector, select_process
from .clock import now_ns


def transcribe(args) -> int:
    # Explicit UTF-8 JSONL, independent of the legacy Windows console codepage.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from app.main import Reporter
    terms = getattr(args, 'course_terms', None)
    terms_override = '' if getattr(args, 'no_course_terms', False) else (str(terms.resolve()) if terms else None)
    config = ASRConfig.load(args.config, model=args.model, language=args.language,
                            device=args.device, compute_type=args.compute_type, course_terms=terms_override)
    report = Reporter(args.log, clock=now_ns)
    try:
        live = args.command == "asr-live"
        realtime = live or args.realtime
        if live:
            found, errors = ProcessSelector().discover(args.source)
            for error in errors:
                report.emit("discovery_error", **error)
            target = select_process(found, args.pid)
            if getattr(args,'expected_created',None) is not None and target.created!=args.expected_created:
                raise ValueError('selected audio source process changed; refresh and select again')
            report.emit("capture_target", pid=target.pid, created=target.created, path=target.path,
                        source=args.source, scope='process_tree')
            source = LiveSource(args.helper, target, args.seconds, config.audio_queue_capacity, report.emit,
                                pause_event=getattr(args,'pause_event',None))
        else:
            source = FileSource(args.input, args.seconds, realtime, config.audio_queue_capacity, report.emit)
        summary = asyncio.run(run_pipeline(config, source, report.emit, realtime))
        return 0 if summary["complete"] and summary["inference_jobs"] > 0 else 3
    except KeyboardInterrupt:
        report.emit("asr_cancelled", complete=False)
        return 130
    except Exception as exc:
        report.emit("asr_error", type=type(exc).__name__, error=str(exc), complete=False)
        return 1
    finally:
        report.close()
