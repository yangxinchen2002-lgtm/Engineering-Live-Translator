"""Generate the remaining native voice presets with the same deployed runtime."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.qwen_tts_lab import TTSSession


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
    session=TTSSession('fast',args.output);rows=[]
    try:
        for voice in ('dylan','eric','ryan','aiden','ono_anna','sohee'):
            text='今天我们学习线性代数。这个矩阵的逆不存在。' if voice in ('dylan','eric') else '你好，这是中文朗读测试。'
            result=session.request({'id':voice,'text':text,'speaker':voice},args.output/f'{voice}.wav')
            rows.append(result);print(voice,'generated',result['duration_s'],flush=True)
    finally:session.close()
    result={'passed':len(rows)==6 and not any(r['possibly_token_limited'] for r in rows),'voices':rows,'ready':session.ready}
    (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
