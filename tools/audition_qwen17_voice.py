"""Same-text 1.7B male voice/style auditions, using the deployed GPU backend."""
import argparse
import gc
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();directory=args.output.resolve();directory.mkdir(parents=True,exist_ok=False)
    import numpy as np
    import soundfile as sf
    from app.speech.config import LECTURE_INSTRUCTION
    from app.speech.runtime import SpeechEngine
    engine=SpeechEngine('cuda',model_size='1.7B');rows=[]
    texts=[('keywords','请注意，这里的矩阵必须是方阵。可惜，这个方法只适用于线性系统。现在先把条件说明清楚，再按顺序介绍计算步骤。'),
           ('lecture','判断系统是否稳定，需要先检查反馈方向。可惜，这个结论在存在时间延迟时并不成立。为什么会这样？我们先说明假设，然后按步骤计算，不必急着得出结论。')]
    try:
        # Discard graph initialization before resetting the same seed for each comparison.
        list(engine.generate('准备好了。','aiden',seed=20261101))
        for group,text in texts:
            for name,speaker,instruct in [('aiden_default','aiden',None),('aiden_lecture','aiden',LECTURE_INSTRUCTION),
                                         ('uncle_fu_lecture','uncle_fu',LECTURE_INSTRUCTION)]:
                engine.torch.manual_seed(20261101);start=time.perf_counter();chunks=[];first=None
                for chunk,rate,_ in engine.model.generate_custom_voice_streaming(text=text,language='Chinese',speaker=speaker,
                            instruct=instruct,non_streaming_mode=True,max_new_tokens=600,chunk_size=8):
                    if first is None:first=time.perf_counter()-start
                    chunks.append(np.asarray(chunk,dtype=np.float32).reshape(-1))
                wave=np.concatenate(chunks);elapsed=time.perf_counter()-start
                if not np.isfinite(wave).all() or len(wave)/rate>47:raise RuntimeError('invalid/truncated audition')
                identity=group+'_'+name;sf.write(directory/f'{identity}.wav',wave,rate,subtype='PCM_16')
                row={'id':identity,'speaker':speaker,'instruct':instruct,'text':text,'file':identity+'.wav',
                     'seed':20261101,'duration_seconds':len(wave)/rate,'first_audio_seconds':first,'generation_seconds':elapsed}
                rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    finally:
        del engine;gc.collect()
        import torch
        torch.cuda.empty_cache()
    (directory/'results.json').write_text(json.dumps({'model_size':'1.7B','cases':rows},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
