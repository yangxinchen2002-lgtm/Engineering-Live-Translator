"""Controlled Chinese playback with real concurrent Whisper; no capture or cloud API."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
FRAGMENTS=[(0,'请注意，'),(500,'这里并不要求矩阵可逆。'),(1500,'我们先说明适用条件。'),
           (8500,'可惜，'),(9000,'这个结论只适用于线性系统。'),(9800,'接下来说明它的适用范围。'),
           (17000,'这里使用 CPU 和 GPU 分担计算任务。'),(18000,'PID 控制器包含比例、积分和微分三个部分。'),
           (25500,'最后，'),(26500,'核对计算条件。'),(33500,'本次讲解结束。')]


def main():
    from app.speech.config import VOICES
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model-size',choices=['0.6B','1.7B'],default='1.7B')
    parser.add_argument('--volume',type=int,default=25)
    parser.add_argument('--voice',choices=[voice for voice,_ in VOICES],default='lecture_male')
    parser.add_argument('--fragments',action='store_true',help='timed short Chinese/mixed fragments, including a final tail')
    parser.add_argument('--burst-transitions',action='store_true',help='prequeued long/short sentences for synthesis/playback overlap')
    parser.add_argument('--controller-source',type=Path,help='explicit prior controller source for a before/after measurement')
    parser.add_argument('--seed',type=int,default=20261102)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    if not 0<=args.volume<=100:parser.error('volume must be between 0 and 100')
    if not 0<=args.seed<2**32:parser.error('seed must be an unsigned 32-bit integer')
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from app.speech.config import SpeechConfig,LECTURE_VOICE
    from app.ui.speech import SpeechController
    if args.controller_source:
        spec=importlib.util.spec_from_file_location('app.ui._benchmark_controller',args.controller_source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);SpeechController=module.SpeechController
    from tools.check_speech_backlog import TEXTS
    from tools.qwen_tts_lab import load_asr,jobs,asr_jobs
    from tools.tts_sampling import Sampler
    sampler=Sampler();sampler.stage='asr_load'
    worker,asr_ready=load_asr();inputs=jobs()
    burst=['首先完整说明这个结论的适用条件，以及每一步计算应当注意的问题。','请注意，',
           '接下来核对矩阵的维数和边界条件，确保每个计算步骤都符合定义。','可惜，',
           '然后把计算结果代入原方程，逐项检查单位和符号，最后说明这个方法的局限。','本次讲解结束。']
    schedule=([(0,text) for text in burst] if args.burst_transitions else
              FRAGMENTS if args.fragments else [(i*4000,text) for i,text in enumerate(TEXTS*2)])
    texts=[text for _,text in schedule]
    app=QApplication([]);speech=SpeechController()
    speech.configure(SpeechConfig(True,'cuda',args.voice,args.volume,1.25,True,args.model_size))
    events=[];problems=[];asr=[];arrivals=[];begins=[];ends=[];finished_ids=[];waits=[];gaps=[];speeds=[]
    commands=[];begin_times={}
    raw_hashes={};original_event=speech._event
    def capture_audio(value):
        if value.get('event')=='speech_audio':
            raw_hashes.setdefault(value['id'],hashlib.sha256()).update(base64.b64decode(value['pcm']))
        original_event(value)
    speech._event=capture_audio
    state={'warming':True,'done':False,'thread':None,'origin':None,'passed':False,'input_finished':False};stop=threading.Event()
    def recognition():
        try:asr.extend(asr_jobs(worker,inputs,until=stop))
        except BaseException as error:problems.append('ASR: '+str(error))
    def offer(index):
        if state['done']:return
        arrivals.append({'text':texts[index],'at':time.monotonic()})
        speech.offer({'session_id':'lecture-playback','segment_id':index,'revision':1,'translated_revision':1,
                      'source_closed':True,'state':'final','translated_text':texts[index]})
        if index==len(texts)-1:QTimer.singleShot(100,finish_inputs)
    def start():
        state['warming']=False;speech.start('lecture-playback');sampler.stage='concurrent_playback'
        state['origin']=time.monotonic();state['thread']=threading.Thread(target=recognition);state['thread'].start()
        for index,(delay,_) in enumerate(schedule):QTimer.singleShot(delay,lambda i=index:offer(i))
    def finish_inputs():
        if not state['done']:
            state['input_finished']=True;speech.finish_input()
    def diagnostic(row):
        now=time.monotonic();events.append({'warming':state['warming'],'at':now,**row})
        print(json.dumps({'warming':state['warming'],**row},ensure_ascii=False),flush=True)
        if state['warming']:
            if row['event']=='speech_playback_finished':QTimer.singleShot(100,start)
            return
        if row['event']=='speech_playback_buffer_started':
            begins.append(row['id']);begin_times[row['id']]=now;speeds.append(row['speed'])
            if ends:gaps.append(now-ends[-1])
        elif row['event']=='speech_playback_finished':
            ends.append(now)
            finished_ids.append(row['id'])
    def inspect():
        if problems:finish()
        elif (state['input_finished'] and speech.finishing and not speech.current
              and not speech.queue and not speech.prefetched):finish()
    def finish():
        if state['done']:return
        state['done']=True;check.stop();speech.close();stop.set()
        thread=state['thread']
        if thread:
            # The ASR helper completes its minimum 24 scheduled public jobs,
            # even when a short speech case finishes earlier than that sweep.
            thread.join(timeout=30)
            if thread.is_alive():problems.append('ASR thread failed to stop')
        worker.close()
        if thread and thread.is_alive():thread.join(timeout=2)
        sampler.stage='cleanup';sampler.close()
        peak=max((r['used_bytes'] for r in sampler.rows if r['stage']=='concurrent_playback'),default=0)
        measured=[row for row in commands if not row['warming']]
        ids=[row['id'] for row in measured]
        text_preserved=''.join(row['text'] for row in measured)==''.join(texts)
        complete=bool(ids and begins==finished_ids==ids and text_preserved)
        cursor=0
        for row in measured:
            position=0
            for arrival in arrivals:
                if position+len(arrival['text'])>cursor:
                    if row['id'] in begin_times:waits.append(begin_times[row['id']]-arrival['at'])
                    break
                position+=len(arrival['text'])
            cursor+=len(row['text'])
        target=bool(len(waits)==len(measured) and waits and max(waits)<8
                    and (args.fragments or statistics.median(waits[-3:])<=statistics.median(waits[:3])+1.5))
        submissions=[r for r in events if not r['warming'] and r['event']=='speech_utterance_submitted']
        merged=sum(r['source_parts']>1 for r in submissions)
        underruns=[r for r in events if not r['warming'] and r['event']=='speech_audio_underrun']
        state['passed']=bool(complete and (args.burst_transitions or target) and merged==0 and not underruns and not problems and not sampler.error and len(asr)>=12)
        result={'passed':state['passed'],'model_size':args.model_size,'voice':args.voice,
                'controller_source':str(args.controller_source) if args.controller_source else 'current',
                'method':('prequeued long/short transitions' if args.burst_transitions else 'timed Chinese/mixed short fragments' if args.fragments else '12 Chinese inputs at four-second intervals')+', actual GPU TTS/Qt output plus real continuous GPU Whisper',
                'complete_in_order':complete,'queue_within_target':target,'sentences_played':len(ends),'texts':texts,
                'input_records':len(texts),'all_text_preserved':text_preserved,'merged_groups':merged,
                'utterance_texts':[row['text'] for row in measured],
                'audio_sha256':{row['id']:raw_hashes[row['id']].hexdigest() for row in measured if row['id'] in raw_hashes},
                'queue_wait_seconds':waits,'queue_wait_max_seconds':max(waits,default=None),
                'queue_wait_median_seconds':statistics.median(waits) if waits else None,
                'within_three_seconds_fraction':sum(wait<=3 for wait in waits)/len(waits) if waits else None,
                'seed':args.seed,
                'first_three_wait_median_seconds':statistics.median(waits[:3]) if len(waits)>=3 else None,
                'last_three_wait_median_seconds':statistics.median(waits[-3:]) if len(waits)>=3 else None,
                'between_sentences_median_seconds':statistics.median(gaps) if gaps else None,'playback_speeds':speeds,
                'whole_gpu_concurrent_peak_bytes':peak,'sampling_error':sampler.error,'asr_ready':asr_ready,
                'intra_utterance_underruns':len(underruns),
                'asr_response_median_seconds':statistics.median(r['response_s'] for r in asr) if asr else None,
                'asr_jobs':asr,'events':events,'problems':problems}
        (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        (args.output/'memory-samples.json').write_text(json.dumps(sampler.rows),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in ('events','asr_jobs','texts')},ensure_ascii=False),flush=True)
        app.quit()
    speech.problem.connect(problems.append);speech.diagnostic.connect(diagnostic)
    check=QTimer();check.setInterval(100);check.timeout.connect(inspect);check.start()
    sampler.stage='tts_warmup'
    speech.enqueue('准备好了。');speech._load()
    original_write=speech.process.write
    def write(data):
        command=json.loads(data);commands.append({'warming':state['warming'],**command})
        command['seed']=args.seed
        return original_write((json.dumps(command,ensure_ascii=False)+'\n').encode('utf-8'))
    speech.process.write=write;speech._next()
    QTimer.singleShot(240000,finish)
    app.exec();return 0 if state['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
