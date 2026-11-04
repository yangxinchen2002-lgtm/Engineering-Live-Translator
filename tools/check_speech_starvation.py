"""Replay measured chunk timing into real Qt audio (muted), comparing before/after.

This is a deterministic playback test, not a new TTS or ASR benchmark. Input PCM
is a continuous tone. Only chunk delivery timing changes between idle/busy cases.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    import numpy as np
    from PySide6.QtCore import QProcess,QTimer
    from PySide6.QtWidgets import QApplication
    from PySide6.QtMultimedia import QAudio
    from app.speech.config import SpeechConfig
    from app.ui.speech import SpeechController
    spec=importlib.util.spec_from_file_location('app.ui._starvation_baseline',args.baseline)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    app=QApplication([]);cases=[('idle','before'),('idle','after'),('busy','before'),('busy','after')]
    rows=[];state={'case':None,'speech':None,'epoch':0,'done':False};rendered=bytearray();gaps=[];events=[];problems=[]
    sample_rate=24000;duration=10.56;count=round(duration*sample_rate)
    pcm=(np.sin(np.arange(count)*2*np.pi*440/sample_rate)*10000).astype('<i2').tobytes()
    packets=[pcm[offset:offset+30720] for offset in range(0,len(pcm),30720)]
    class Process:
        def write(self,data):return len(data)
        def state(self):return QProcess.NotRunning
        def deleteLater(self):pass
    def start_case():
        index=len(rows);load,version=cases[index];state['case']=(load,version);state['epoch']+=1;epoch=state['epoch']
        cls=old.SpeechController if version=='before' else SpeechController
        speech=cls();state['speech']=speech;rendered.clear();gaps.clear();events.clear();problems.clear()
        speech.configure(SpeechConfig(True,'cuda','lecture_male',0,1.6,False,'0.6B'))
        speech.ready=True;speech.active=True;speech.process=Process();speech.problem.connect(problems.append)
        original_append=speech._append_pcm
        def capture(chunks):
            chunks=list(chunks)
            for chunk in chunks:rendered.extend(chunk)
            original_append(chunks)
        speech._append_pcm=capture
        state.update(origin=time.monotonic(),first=None,gap_start=None,format=None)
        def diagnostic(row):
            events.append(row)
            if row['event']=='speech_playback_buffer_started':
                state['first']=time.monotonic()-state['origin']
                state['format']={'rate':speech.output_rate,'frame_bytes':speech.frame_bytes}
            elif row['event']=='speech_playback_finished':QTimer.singleShot(50,complete_case)
        speech.diagnostic.connect(diagnostic)
        speech.offer({'session_id':'replay','segment_id':0,'revision':1,'translated_revision':1,
                      'source_closed':True,'state':'final','translated_text':'请注意，判断系统是否稳定，需要先检查反馈方向，再核对边界条件，最后用实验验证计算结果。'})
        speech.finish_input()  # One-record stream: isolate audio buffering from text look-ahead.
        first=.3583867 if load=='idle' else .56845
        generation=duration*.48258129166666663 if load=='idle' else 9.4772456
        produced=0.;packet_duration=len(packets[0])/2/sample_rate
        rate=(generation-first)/(duration-packet_duration)
        for index,packet in enumerate(packets):
            produced+=len(packet)/2/sample_rate;due=first+(produced-packet_duration)*rate
            def deliver(data=packet,last=index==len(packets)-1,token=epoch):
                if state['done'] or token!=state['epoch']:return
                speech._event({'event':'speech_audio','id':'1','rate':sample_rate,'pcm':base64.b64encode(data).decode()})
                if last:speech._event({'event':'speech_done','id':'1','audio_seconds':duration,'generation_seconds':generation})
            QTimer.singleShot(round(due*1000),deliver)
        print(json.dumps({'case':load,'version':version,'generation_seconds':generation}),flush=True)
    def inspect():
        speech=state['speech']
        if not speech:return
        now=time.monotonic()
        empty=bool(speech.sink and speech.current and speech.current.get('playing') and not speech.audio_done
                   and speech.sink.state()==QAudio.State.IdleState and speech.sink.processedUSecs()>0)
        if empty and state['gap_start'] is None:state['gap_start']=now
        elif not empty and state['gap_start'] is not None:
            gaps.append(now-state['gap_start']);state['gap_start']=None
        if problems or now-state['origin']>30:complete_case()
    def complete_case():
        speech=state['speech']
        if not speech:return
        state['speech']=None;state['epoch']+=1
        if state['gap_start'] is not None:gaps.append(time.monotonic()-state['gap_start'])
        row={'load':state['case'][0],'version':state['case'][1],'first_buffer_seconds':state['first'],
             'elapsed_seconds':time.monotonic()-state['origin'],'underrun_intervals_seconds':[gap for gap in gaps if gap>.03],
             'underrun_seconds':sum(gap for gap in gaps if gap>.03),'audio_sha256':hashlib.sha256(rendered).hexdigest(),
             'rendered_bytes':len(rendered),'format':state['format'],'events':list(events),'problems':list(problems),
             'completed':any(event['event']=='speech_playback_finished' for event in events)}
        rows.append(row);speech.close();speech.deleteLater()
        print(json.dumps({key:value for key,value in row.items() if key!='events'}),flush=True)
        if len(rows)==len(cases):finish()
        else:QTimer.singleShot(250,start_case)
    def finish():
        state['done']=True;poll.stop()
        passed=(len(rows)==4 and all(row['completed'] and not row['problems'] for row in rows)
                and rows[2]['underrun_seconds']>.2 and rows[3]['underrun_seconds']<.08
                and all(rows[index]['audio_sha256']==rows[index+1]['audio_sha256'] for index in (0,2)))
        result={'passed':passed,'method':__doc__,'cases':rows}
        (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        state['passed']=passed;print(json.dumps({'passed':passed}),flush=True);app.quit()
    poll=QTimer();poll.setInterval(5);poll.timeout.connect(inspect);poll.start()
    QTimer.singleShot(0,start_case);app.exec();return 0 if state.get('passed') else 2


if __name__=='__main__':raise SystemExit(main())
