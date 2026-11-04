"""Offline male lecture-voice comparison; acoustic metrics do not rate emotion/naturalness."""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('NUMBA_NUM_THREADS','4')
TEXT='请注意，这里的矩阵必须是方阵。可惜，这个方法只适用于线性系统。现在先把条件说明清楚，再按顺序介绍计算步骤。'
CASES=[('ryan_original','ryan',{}),('uncle_fu_original','uncle_fu',{}),('dylan_original','dylan',{}),
       ('aiden_original','aiden',{}),('uncle_fu_restrained','uncle_fu',{'temperature':.6,'top_k':30,'top_p':.85}),
       ('dylan_restrained','dylan',{'temperature':.6,'top_k':30,'top_p':.85}),
       ('uncle_fu_greedy','uncle_fu',{'do_sample':False})]
CANDIDATES=[('ryan_original','ryan',{}),('aiden_original','aiden',{}),
            ('aiden_restrained','aiden',{'temperature':.6,'top_k':30,'top_p':.85}),
            ('uncle_fu_restrained','uncle_fu',{'temperature':.6,'top_k':30,'top_p':.85})]
FOLLOW_UP=[
    ('lecture','请注意，判断系统是否稳定，需要先检查反馈方向。可惜，这个结论在存在时间延迟时并不成立。为什么会这样？我们先说明假设，然后按步骤计算，不必急着得出结论。'),
    ('mixed','我们使用 Transformer 模型处理输入，通过 CPU 和 GPU 分担计算。这里的 PID 控制器包含比例、积分和微分三个部分。请注意，采样频率是48000赫兹，误差不超过0.5%。'),
]


def acoustics(wave,rate):
    import librosa
    import numpy as np
    pitch,voiced,probability=librosa.pyin(wave,sr=rate,fmin=55,fmax=400,frame_length=1536,hop_length=240,center=False)
    valid=pitch[voiced & np.isfinite(pitch)]
    notes=12*np.log2(valid/100) if len(valid) else np.array([])
    width=round(rate*.02);rms=np.array([np.sqrt(np.mean(wave[i:i+width].astype('float64')**2)) for i in range(0,len(wave),width)])
    quiet=rms<.002;runs=[];run=0
    for value in quiet:
        if value:run+=1
        elif run:runs.append(run*.02);run=0
    if run:runs.append(run*.02)
    return {'pitch_median_hz':float(np.median(valid)) if len(valid) else None,
            'pitch_iqr_semitones':float(np.percentile(notes,75)-np.percentile(notes,25)) if len(notes) else None,
            'pitch_p90_p10_semitones':float(np.percentile(notes,90)-np.percentile(notes,10)) if len(notes) else None,
            'quiet_runs_over_300ms':[round(r,3) for r in runs if r>.3],
            'quiet_seconds_over_300ms':sum(r for r in runs if r>.3),
            'note':'Pitch estimation and low-energy runs only; not an emotion or human naturalness score.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--follow-up',action='store_true')
    args=parser.parse_args();directory=args.output.resolve();directory.mkdir(parents=True,exist_ok=False)
    import numpy as np
    import soundfile as sf
    from app.speech.runtime import SpeechEngine
    engine=SpeechEngine('cuda');rows=[]
    try:
        cases=[(identity,voice,options,TEXT,20261101) for identity,voice,options in CASES]
        if args.follow_up:
            cases=[(group+'_'+identity,voice,options,text,20261102+i)
                   for i,(group,text) in enumerate(FOLLOW_UP) for identity,voice,options in CANDIDATES]
        for identity,voice,options,text,seed in cases:
            engine.torch.manual_seed(seed);started=time.perf_counter();chunks=[];first=None
            for chunk,rate,_ in engine.model.generate_custom_voice_streaming(text=text,speaker=voice,language='Chinese',
                non_streaming_mode=True,max_new_tokens=600,chunk_size=8,**options):
                if first is None:first=time.perf_counter()-started
                chunks.append(np.asarray(chunk,dtype=np.float32).reshape(-1))
            elapsed=time.perf_counter()-started;wave=np.concatenate(chunks)
            if not np.isfinite(wave).all() or len(wave)/rate>47:raise RuntimeError('invalid/truncated voice sample')
            sf.write(directory/f'{identity}.wav',wave,rate,subtype='PCM_16')
            row={'id':identity,'voice':voice,'options':options,'seed':seed,'text':text,'duration_seconds':len(wave)/rate,
                 'first_audio_seconds':first,'generation_seconds':elapsed,'file':identity+'.wav'}
            rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    finally:
        del engine;gc.collect()
        import torch
        torch.cuda.empty_cache()
    for row in rows:
        wave,rate=sf.read(directory/row['file'],dtype='float32');row['acoustics']=acoustics(wave,rate)
        print(json.dumps({'id':row['id'],**row['acoustics']},ensure_ascii=False),flush=True)
    (directory/'results.json').write_text(json.dumps({'cases':rows},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
