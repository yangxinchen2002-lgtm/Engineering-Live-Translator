"""Generate the integrated lecture preset on GPU/CPU and render its real playback path."""
import argparse
import json
from pathlib import Path
import sys
import wave

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.qwen_tts_lab import TTSSession
from app.speech.config import LECTURE_VOICE
from app.speech.playback import PlaybackConverter


def render(source,target,speed,*,compact_pauses=True):
    with wave.open(str(source),'rb') as reader:
        rate=reader.getframerate();pcm=reader.readframes(reader.getnframes())
    converter=PlaybackConverter(rate,rate,1,'s16',speed,compact_pauses=compact_pauses)
    chunks=[c for i in range(0,len(pcm),4800) for c in converter.convert(pcm[i:i+4800])]
    chunks.extend(converter.convert(b''));output=b''.join(chunks)
    with wave.open(str(target),'wb') as writer:
        writer.setparams((1,2,rate,0,'NONE','not compressed'));writer.writeframes(output)
    return {'file':target.name,'speed':speed,'duration_seconds':len(output)/2/rate,
            'near_silence_removed_seconds':converter.pause_compactor.removed_samples/rate if converter.pause_compactor else 0.}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--device',choices=['cuda','cpu'],required=True)
    parser.add_argument('--model-size',choices=['0.6B','1.7B'],default='0.6B');args=parser.parse_args()
    directory=args.output.resolve();directory.mkdir(parents=True,exist_ok=False)
    text='请注意，这里的矩阵必须是方阵。可惜，这个方法不适用。'
    cases=[('chinese',text)]
    if args.device=='cuda':
        cases.append(('mixed','我们使用 Transformer 模型处理输入，通过 CPU 和 GPU 分担计算。这里的 PID 控制器包含比例、积分和微分三个部分。请注意，采样频率是48000赫兹，误差不超过0.5%。'))
    session=TTSSession('fast' if args.device=='cuda' else 'official',directory,device=args.device,model_size=args.model_size)
    rows=[]
    try:
        print(json.dumps({'ready':session.ready},ensure_ascii=False),flush=True)
        for identity,text in cases:
            result=session.request({'id':identity,'text':text,'speaker':LECTURE_VOICE,'seed':20261103},directory/f'{identity}_raw.wav')
            result['rendered']=[render(Path(result['output']),directory/f'{identity}_{speed:.2f}x.wav',speed) for speed in (1.,1.25)]
            rows.append(result)
            print(json.dumps({k:v for k,v in result.items() if k!='chunks'},ensure_ascii=False),flush=True)
    finally:session.close()
    (directory/'results.json').write_text(json.dumps({'ready':session.ready,'cases':rows},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
