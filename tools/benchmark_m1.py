"""Serial real-time file benchmark, no playback/no cloud; explicit new evidence directory."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.asr.evaluation import evaluate


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=900)
    p.add_argument('--languages',nargs='+',choices=['de','en'],default=['de','en'])
    a=p.parse_args()
    a.output=a.output.resolve()
    if a.seconds <= 0:p.error('seconds must be positive')
    a.output.mkdir(parents=True,exist_ok=False)
    packages=['numpy','scipy','faster-whisper','ctranslate2','onnxruntime','av','huggingface-hub','tokenizers','setuptools','jiwer','rapidfuzz']
    hashes={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (ROOT/'app').rglob('*.py')}
    environment={'python':sys.version,'platform':platform.platform(),
                 'packages':{n:importlib.metadata.version(n) for n in packages},'source_sha256':hashes}
    (a.output/'environment.json').write_text(json.dumps(environment,indent=2),encoding='utf-8')
    fixtures=ROOT/'tests/fixtures/public-m1'
    summaries=[]
    for lang in a.languages:
        stem='de-open-source-firmware' if lang=='de' else 'en-linear-algebra'
        media=fixtures/(stem+('.mp3' if lang=='de' else '.mp4'))
        reference=fixtures/(stem+('.srt' if lang=='de' else '.vtt'))
        terms=(['Firmware','Prozessor','Speicher','BIOS','UEFI','Intel','Kernel','Betriebssystem'] if lang=='de'
               else ['matrix','matrices','vector','vectors','linear','equation','equations','column','row'])
        log=a.output/(lang+'.jsonl')
        print(json.dumps({'starting_language':lang,'seconds':a.seconds}),flush=True)
        started=time.monotonic()
        with (a.output/(lang+'.stdout.txt')).open('xb') as out,(a.output/(lang+'.stderr.txt')).open('xb') as err:
            result=subprocess.run([sys.executable,'-X','utf8','-m','app.main','asr-file','--input',str(media),
                                   '--language',lang,'--seconds',str(a.seconds),'--realtime','--log',str(log)],
                                  cwd=ROOT,stdout=out,stderr=err,timeout=a.seconds+240)
        if result.returncode:
            raise RuntimeError(f'{lang} benchmark failed, exit={result.returncode}; inspect {log}')
        report=evaluate(log,reference,a.seconds,terms)
        report['benchmark_wall_seconds']=time.monotonic()-started
        (a.output/(lang+'-report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        summaries.append(report)
        print(json.dumps({'finished_language':lang,'score':report['score'],'run':report['run']},ensure_ascii=True),flush=True)
    (a.output/'reports.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
