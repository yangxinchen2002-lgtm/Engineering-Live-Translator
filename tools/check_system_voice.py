"""Real offline SAPI worker check. No source capture, cloud or Qwen model."""
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
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--language',choices=('zh','en'),default='zh');args=parser.parse_args()
    from app.web_follow.speech import voices_for
    voices=voices_for(args.language)
    if not voices:raise RuntimeError('No Windows voice available for the selected language')
    index=voices[0]['id'];started=time.perf_counter()
    text='这是 Windows 中文系统音色。字幕继续跟随视频。' if args.language=='zh' else 'This is the English system voice. Subtitles follow the video.'
    commands=[dict(id='test',text=text,voice='serena'),dict(command='stop')]
    result=subprocess.run([sys.executable,'-B','-X','utf8','-m','app.speech.worker','--engine','system','--language',args.language,'--device','cpu','--system-voice',str(index)],
        cwd=ROOT,input=''.join(json.dumps(c,ensure_ascii=False)+'\n' for c in commands),capture_output=True,encoding='utf-8',timeout=30)
    events=[json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if result.returncode or any(e['event']=='speech_error' for e in events):raise RuntimeError('系统语音工作进程测试失败：'+str([e for e in events if e['event']=='speech_error']))
    ready=next(e for e in events if e['event']=='speech_ready');done=next(e for e in events if e['event']=='speech_done')
    blocks=[e for e in events if e['event']=='speech_audio'];pcm=b''.join(base64.b64decode(e['pcm'],validate=True) for e in blocks)
    samples=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768
    assert ready['engine']=='windows-sapi' and ready['device']=='cpu' and all(e['rate']==16000 for e in blocks)
    rms=float(np.sqrt(np.mean(samples**2)));assert samples.size>16000 and rms>.001
    report=dict(language=args.language,voices=len(voices),voice_label=voices[0]['label'],engine=ready['engine'],device=ready['device'],
        sample_rate=16000,samples=int(samples.size),audio_seconds=done['audio_seconds'],rms=rms,
        elapsed_seconds=round(time.perf_counter()-started,3),worker_exited=True,cloud_requests=0,audio_saved=False)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
