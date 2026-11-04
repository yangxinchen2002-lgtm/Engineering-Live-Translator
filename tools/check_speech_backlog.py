"""Controlled continuous Chinese text -> real GPU generation and Qt playback, before/after.

This tests only local speech, not video capture, ASR, translation or any cloud API.
The baseline is an explicit prior source snapshot, not copied into production.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.speech.config import SpeechConfig
from app.ui.speech import SpeechController

TEXTS=['今天我们学习矩阵，先看两个方程和两个未知数。',
       '第一个方程是二乘以 x 减去 y 等于零。',
       '第二个方程是负 x 加上二乘以 y 等于三。',
       '系数矩阵第一行是二和负一，第二行是负一和二。',
       '请注意，系数矩阵不包含等号右边的常数。',
       '接下来把未知数写成向量，再检查方程是否成立。']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cycles',type=int,default=1)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    if not 1<=args.cycles<=3:parser.error('choose one to three cycles')
    texts=TEXTS*args.cycles
    spec=importlib.util.spec_from_file_location('app.ui._baseline_speech',args.baseline)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    app=QApplication([]);results={};events=[];state={'phase':'before','warming':True,'complete':False}
    controller=[None];arrivals={};begins=[];ends=[];gaps=[];waits=[];durations=[];speeds=[];problems=[];origin=[None]
    def run():
        phase=state['phase'];state['warming']=True;arrivals.clear();begins.clear();ends.clear();gaps.clear();waits.clear();durations.clear();speeds.clear();problems.clear()
        speech=(module.SpeechController if phase=='before' else SpeechController)();controller[0]=speech
        speech.configure(SpeechConfig(True,'cuda','uncle_fu',25,1. if phase=='before' else 1.25,phase!='before'))
        speech.problem.connect(problems.append);speech.diagnostic.connect(diagnostic)
        if phase=='before':speech.queue.append('准备好了。')
        else:speech.enqueue('准备好了。')
        speech._load()
        write=speech.process.write
        def fixed_seed(data):
            command=json.loads(data)
            command['seed']=20261101+int(command['id'])
            return write((json.dumps(command,ensure_ascii=False)+'\n').encode('utf-8'))
        speech.process.write=fixed_seed;speech._next()
    def offer(index):
        if state['complete']:return
        arrivals[str(index+2)]=time.monotonic()
        controller[0].offer({'session_id':'backlog-test','segment_id':index,'revision':1,'translated_revision':1,
                             'source_closed':True,'state':'final','translated_text':texts[index]})
    def start_inputs():
        origin[0]=time.monotonic();controller[0].active=True;controller[0].session='backlog-test'
        for index in range(len(texts)):QTimer.singleShot(index*4000,lambda i=index:offer(i))
    def diagnostic(row):
        phase=state['phase'];now=time.monotonic();events.append({'phase':phase,'warming':state['warming'],'at':now,**row})
        if state['warming']:
            if row['event']=='speech_playback_finished':
                state['warming']=False;QTimer.singleShot(200,start_inputs)
            return
        if row['event']=='speech_playback_buffer_started':
            begins.append(row['id']);waits.append(now-arrivals[row['id']]);speeds.append(row.get('speed',1.))
            if ends:gaps.append(now-ends[-1])
        elif row['event']=='speech_done':durations.append(row['audio_seconds'])
        elif row['event']=='speech_playback_finished':
            ends.append(now)
            if len(ends)==len(texts):QTimer.singleShot(100,case_done)
    def case_done():
        phase=state['phase'];speech=controller[0]
        results[phase]={'complete_in_order':begins==[str(i+2) for i in range(len(texts))],
                        'sentences_played':len(ends),'problems':list(problems),
                        'elapsed_from_first_input_s':ends[-1]-origin[0],
                        'queue_wait_p50_s':statistics.median(waits),'queue_wait_max_s':max(waits),
                        'queue_wait_by_sentence_s':list(waits),
                        'between_sentences_p50_s':statistics.median(gaps),'between_sentences_max_s':max(gaps),
                        'model_audio_seconds':list(durations),'playback_speeds':list(speeds),
                        'prefetch_events':sum(r['event']=='speech_prefetch_started' for r in events if r['phase']==phase and not r['warming'])}
        speech.close();speech.deleteLater();controller[0]=None
        print(json.dumps({'phase':phase,**results[phase]},ensure_ascii=False),flush=True)
        if phase=='before':state['phase']='after';QTimer.singleShot(800,run)
        else:finish()
    def finish():
        if state['complete']:return
        state['complete']=True
        passed=(len(results)==2 and all(r['complete_in_order'] and not r['problems'] for r in results.values())
                and results['after']['between_sentences_p50_s']<results['before']['between_sentences_p50_s']
                and results['after']['queue_wait_max_s']<results['before']['queue_wait_max_s']
                and results['after']['prefetch_events']>0)
        document={'passed':passed,'method':f'{len(texts)} controlled Chinese inputs every four seconds, same voice and per-utterance random seed, real local GPU and Qt audio',
                  'texts':texts,'results':results,'events':events,'unfinished_problems':list(problems)}
        (args.output/'results.json').write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
        if controller[0]:controller[0].close()
        app.quit()
    QTimer.singleShot(100,run);QTimer.singleShot(300000,finish)
    app.exec();return 0 if json.loads((args.output/'results.json').read_text(encoding='utf-8'))['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
