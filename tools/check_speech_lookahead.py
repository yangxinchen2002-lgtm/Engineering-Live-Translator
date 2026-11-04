"""Deterministic long/short synthesis scheduling replay into real muted Qt audio."""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    import numpy as np
    from PySide6.QtCore import QProcess,QTimer
    from PySide6.QtWidgets import QApplication
    from app.ui.speech import SpeechController
    from app.speech.config import SpeechConfig
    spec=importlib.util.spec_from_file_location('app.ui._lookahead_baseline',args.baseline)
    before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)
    app=QApplication([]);rate=24000
    texts=['先完整说明计算条件。','请注意，','接下来按顺序检查每一步计算。','可惜，','然后核对边界条件。','最后验证结果。']
    durations=[6.,.64,6.,.64,4.,.64]
    rows=[];state={'speech':None,'phase':'before','token':0,'done':False};events=[];problems=[];gaps=[];rendered=bytearray()
    def start():
        state['token']+=1;token=state['token'];events.clear();problems.clear();gaps.clear();rendered.clear()
        cls=before.SpeechController if state['phase']=='before' else SpeechController
        speech=cls();state.update(speech=speech,worker=None,finished=[],started=[],last_end=None,origin=time.monotonic())
        speech.configure(SpeechConfig(True,'cuda','lecture_male',0,1.6,False,'1.7B'))
        speech.active=True;speech.ready=True;speech.session='lookahead-replay';speech.problem.connect(problems.append)
        original_append=speech._append_pcm
        def capture(chunks):
            chunks=list(chunks)
            for chunk in chunks:rendered.extend(chunk)
            original_append(chunks)
        speech._append_pcm=capture
        def diagnostic(row):
            events.append({'at':time.monotonic(),**row})
            if row['event']=='speech_playback_buffer_started':
                state['started'].append(row['id'])
                if state['last_end'] is not None:gaps.append(time.monotonic()-state['last_end'])
            elif row['event']=='speech_playback_finished':
                state['last_end']=time.monotonic();state['finished'].append(row['id'])
                if len(state['finished'])==len(texts):QTimer.singleShot(30,complete)
        speech.diagnostic.connect(diagnostic)
        class Process:
            def write(self,data):
                command=json.loads(data);identity=command['id'];index=int(identity)-1
                if state['worker'] is not None:problems.append('overlapping synthesis requests')
                state['worker']=identity
                duration=durations[index];count=round(duration*rate)
                wave=(np.sin(np.arange(count)*2*np.pi*(400+index*30)/rate)*10000).astype('<i2').tobytes()
                packets=[wave[offset:offset+30720] for offset in range(0,len(wave),30720)]
                generation=.4+max(0,duration-.64)*.45
                produced=0.
                for offset,packet in enumerate(packets):
                    produced+=len(packet)/2/rate
                    due=.4+max(0,produced-.64)*.45
                    def deliver(pcm=packet,last=offset==len(packets)-1):
                        if state['done'] or token!=state['token']:return
                        speech._event({'event':'speech_audio','id':identity,'rate':rate,'pcm':base64.b64encode(pcm).decode()})
                        if last:
                            state['worker']=None
                            speech._event({'event':'speech_done','id':identity,'audio_seconds':duration,
                                           'first_audio_seconds':.4,'generation_seconds':generation})
                    QTimer.singleShot(round(due*1000),deliver)
                return len(data)
            def state(self):return QProcess.NotRunning
            def deleteLater(self):pass
        speech.process=Process()
        for index,text in enumerate(texts):
            speech.offer({'session_id':'lookahead-replay','segment_id':index,'revision':1,'translated_revision':1,
                          'source_closed':True,'state':'final','translated_text':text})
        speech.finish_input()
    def complete():
        speech=state['speech']
        if speech is None:return
        state['speech']=None;state['token']+=1
        row={'phase':state['phase'],'complete_in_order':state['started']==state['finished']==[str(i+1) for i in range(len(texts))],
             'gaps_seconds':list(gaps),'gap_median_seconds':statistics.median(gaps) if gaps else None,
             'gap_max_seconds':max(gaps,default=None),'elapsed_seconds':time.monotonic()-state['origin'],
             'audio_sha256':hashlib.sha256(rendered).hexdigest(),'rendered_bytes':len(rendered),
             'underruns':sum(e['event']=='speech_audio_underrun' for e in events),
             'events':list(events),'problems':list(problems)}
        rows.append(row);speech.close();speech.deleteLater()
        print(json.dumps({k:v for k,v in row.items() if k!='events'}),flush=True)
        if state['phase']=='before':state['phase']='after';QTimer.singleShot(250,start)
        else:finish()
    def inspect():
        if state['speech'] and (problems or time.monotonic()-state['origin']>40):complete()
    def finish():
        state['done']=True;poll.stop()
        passed=(len(rows)==2 and all(r['complete_in_order'] and not r['problems'] and r['underruns']==0 for r in rows)
                and rows[0]['audio_sha256']==rows[1]['audio_sha256']
                and rows[1]['gap_max_seconds']<rows[0]['gap_max_seconds']*.5)
        result={'passed':passed,'method':__doc__,'synthesis':'serial simulated 0.4s prefill / 0.45s per second audio; actual muted output; not a model speed benchmark',
                'results':rows}
        (args.output/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');state['passed']=passed;app.quit()
    poll=QTimer();poll.setInterval(50);poll.timeout.connect(inspect);poll.start();QTimer.singleShot(0,start)
    app.exec();return 0 if state.get('passed') else 2


if __name__=='__main__':raise SystemExit(main())
