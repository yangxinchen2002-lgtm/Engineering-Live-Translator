"""Local PCM JSONL worker. It joins the GUI's lifetime job before loading a model."""
import argparse
import base64
import contextlib
import json
import os
import sys
import time


def emit(event,**fields):
    sys.__stdout__.write(json.dumps({'event':event,**fields},ensure_ascii=False)+'\n');sys.__stdout__.flush()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--device',choices=['cuda','cpu'],required=True)
    parser.add_argument('--model-size',choices=['0.6B','1.7B'],default='0.6B')
    parser.add_argument('--engine',choices=['qwen','system'],default='qwen')
    parser.add_argument('--system-voice',type=int,default=-1)
    parser.add_argument('--language',choices=['zh','en'],default='zh')
    args=parser.parse_args()
    from app.ui.lifetime import JOB_ENV,join_owner_job
    if os.environ.get(JOB_ENV):join_owner_job(os.environ[JOB_ENV])
    phase='load'
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if args.engine=='system':
                from .system import SystemSpeechEngine
                engine=SystemSpeechEngine(args.system_voice,args.model_size,language=args.language)
            else:
                from .runtime import SpeechEngine
                engine=SpeechEngine(args.device,model_size=args.model_size,language=args.language)
        emit('speech_ready',**engine.info)
        phase='generate'
        for line in sys.stdin:
            if len(line)>32768:raise ValueError('speech command exceeds limit')
            value=json.loads(line)
            if value.get('command')=='stop':break
            identity=value['id'];start=time.perf_counter_ns();count=0;rate=0;first=None
            seed=value.get('seed')
            if seed is not None and (type(seed) is not int or not 0<=seed<2**32):raise ValueError('invalid speech seed')
            with contextlib.redirect_stdout(sys.stderr):
                for wave,rate in engine.generate(value['text'],value['voice'],seed=seed):
                    import numpy as np
                    if not np.isfinite(wave).all():raise RuntimeError('non-finite speech samples')
                    ready=time.perf_counter_ns()
                    if first is None:first=ready
                    pcm=(np.clip(wave,-1,1)*32767).astype('<i2').tobytes();count+=len(wave)
                    emit('speech_audio',id=identity,rate=rate,pcm=base64.b64encode(pcm).decode('ascii'),ready_ns=ready)
            if not count:raise RuntimeError('empty speech output')
            if count/rate>=1024*.08*.97:raise RuntimeError('speech reached its generation limit')
            emit('speech_done',id=identity,first_audio_seconds=(first-start)/1e9,
                 generation_seconds=(time.perf_counter_ns()-start)/1e9,audio_seconds=count/rate)
        return 0
    except Exception as error:
        code='cuda_out_of_memory' if 'out of memory' in str(error).lower() else type(error).__name__
        emit('speech_error',code=code,stage=phase,message=str(error)[:500]);return 2


if __name__=='__main__':raise SystemExit(main())
