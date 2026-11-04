"""Offline Whisper readback of audition WAVs; does not assess voice naturalness."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path);parser.add_argument('--words',action='store_true');args=parser.parse_args()
    from app.asr.worker import configure_gpu_runtime
    configure_gpu_runtime()
    from faster_whisper import WhisperModel
    model=WhisperModel(str(ROOT/'models/large-v3-turbo'),device='cuda',compute_type='float16',local_files_only=True)
    rows=[]
    for path in sorted(args.directory.glob('*.wav')):
        start=time.perf_counter()
        segments,_=model.transcribe(str(path),language='zh',temperature=0.,beam_size=3,
                                    condition_on_previous_text=False,vad_filter=False,word_timestamps=args.words)
        segments=list(segments)
        row={'file':path.name,'recognized':''.join(s.text for s in segments).strip(),
             'seconds':time.perf_counter()-start}
        if args.words:row['words']=[{'text':word.word,'start':word.start,'end':word.end} for segment in segments for word in segment.words or []]
        rows.append(row);print(json.dumps({k:v for k,v in row.items() if k!='words'},ensure_ascii=False),flush=True)
    (args.directory/'readback.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
