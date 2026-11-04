import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.asr.evaluation import evaluate

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument('--log',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--seconds',type=float,default=900)
    p.add_argument('--terms',nargs='*',default=[])
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--reference-latency',action='store_true',help='only for paced-file --realtime traces')
    args=p.parse_args()
    result=evaluate(args.log,args.reference,args.seconds,args.terms)
    if args.reference_latency:
        from app.asr.latency_evaluation import reference_latency
        result['reference_latency']=reference_latency(args.log,args.reference,args.seconds)
    with args.output.open('x',encoding='utf-8') as out:json.dump(result,out,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=True))
