"""Real offline Qwen speech generation, with no source capture or saved audio."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--language',choices=('zh','en'),default='en')
    args=parser.parse_args()
    from app.speech.config import PYTHON
    text='The matrix has two positive eigenvalues.' if args.language=='en' else '这个矩阵有两个正特征值。'
    commands=[dict(id='check',text=text,voice='aiden'),dict(command='stop')]
    started=time.perf_counter()
    result=subprocess.run([str(PYTHON),'-u','-B','-X','utf8','-m','app.speech.worker',
        '--engine','qwen','--model-size','0.6B','--language',args.language,'--device','cuda'],
        cwd=ROOT,input=''.join(json.dumps(c)+'\n' for c in commands),capture_output=True,encoding='utf-8',
        timeout=150,creationflags=subprocess.CREATE_NO_WINDOW,errors='replace')
    events=[json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if result.returncode or any(e['event']=='speech_error' for e in events):
        raise RuntimeError('Real Qwen speech check failed; no success report written')
    ready=next(e for e in events if e['event']=='speech_ready')
    done=next(e for e in events if e['event']=='speech_done')
    blocks=[e for e in events if e['event']=='speech_audio']
    samples=np.frombuffer(b''.join(base64.b64decode(e['pcm'],validate=True) for e in blocks),dtype='<i2').astype(np.float32)/32768
    rms=float(np.sqrt(np.mean(samples**2)))
    assert ready['language']==args.language and ready['device']=='cuda' and samples.size>24000 and rms>.001
    report=dict(language=args.language,engine=ready['engine'],model_size=ready['model_size'],voice='aiden',
        device=ready['device'],samples=int(samples.size),sample_rates=sorted({e['rate'] for e in blocks}),
        rms=rms,audio_seconds=done['audio_seconds'],elapsed_seconds=round(time.perf_counter()-started,3),
        worker_exited=True,cloud_requests=0,audio_saved=False,recognizer_loaded=False,
        listening_assessment='not performed')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n','utf-8');print(json.dumps(report));return 0


if __name__=='__main__':raise SystemExit(main())
