"""Real CUDA/public-file continuous media-clock test. Never controls a user video."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=int,default=35)
    args=p.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    from app.web_follow.server import Lab
    import psutil
    lab=Lab();pid=None;result={'fixture':'existing public English linear algebra MP4',
        'method':'Explicit test media clock; warmup held at 20 seconds, then advances continuously at 1x',
        'measures':'Backend readiness relative to each ASR sentence start, not browser render or human alignment',
        'narration':False,'cloud':'Real saved DeepSeek key; text only'}
    source_seen={};translation_seen={};rows=[];started=time.monotonic()
    try:
        lab.start(dict(source=str(ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4'),position=20,
            language='en',provider='deepseek',model='deepseek-flash',translate=True,narrate=False,voice=0,lookahead=15))
        pid=lab.process.pid;deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            lab.clock(dict(position=20,paused=True,rate=1,seek=False));state=lab.state()
            if state['status']=='error':raise RuntimeError(state['error'])
            if state['prepared_until']>=35 and state['cues'] and all(c['translation'] for c in state['cues'] if c['asr_confirmed']):break
            time.sleep(.1)
        else:raise TimeoutError('warmup deadline')
        result['initial_warmup_seconds']=round(time.monotonic()-started,3);run=time.monotonic()
        while time.monotonic()-run<args.seconds:
            position=20+time.monotonic()-run
            lab.clock(dict(position=position,paused=False,rate=1,seek=False));state=lab.state()
            if state['status']=='error':raise RuntimeError(state['error'])
            for cue in state['cues']:
                if not cue['asr_confirmed']:continue
                source_seen.setdefault(cue['id'],(cue['start'],position))
                if cue['translation']:translation_seen.setdefault(cue['id'],(cue['start'],position))
            rows.append(dict(position=round(position,3),source_ahead=round(state['source_ahead_seconds'],3),
                translation_ahead=round(state['translation_ahead_seconds'],3),queue=state['metrics'].get('translation_queue',0),
                skips=state['metrics'].get('expired_windows_skipped',0),source_prepare=state['metrics'].get('source_preparation_seconds')))
            time.sleep(.1)
        def summary(items):
            observed=[max(0,arrived-start) for start,arrived in items.values() if 20<=start<20+args.seconds]
            return {'sentences':len(observed),'late_over_250ms':sum(n>.25 for n in observed),'max_lateness_seconds':round(max(observed,default=0),3)}
        result.update(seconds=args.seconds,source_readiness=summary(source_seen),translation_readiness=summary(translation_seen),
            minimum_source_ahead=round(min(r['source_ahead'] for r in rows),3),
            minimum_translation_ahead=round(min(r['translation_ahead'] for r in rows),3),
            skipped_windows=rows[-1]['skips'],usage=state['metrics'].get('usage',{}),samples=rows)
    finally:
        lab.close();result['worker_reaped']=not pid or not psutil.pid_exists(pid)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','usage')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
