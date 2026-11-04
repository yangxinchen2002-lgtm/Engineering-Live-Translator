"""Real 0.6B GPU -> 1.7B GPU -> 1.7B CPU -> 0.6B GPU playback and worker release."""
import argparse
import base64
import json
from pathlib import Path
import sys
import time
import wave

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    import psutil
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from app.ui.speech import SpeechController
    from app.speech.config import SpeechConfig,LECTURE_VOICE
    from tools.check_lecture_voice_profile import render
    app=QApplication([]);speech=SpeechController();cases=[('0.6B','cuda'),('1.7B','cuda'),('1.7B','cpu'),('0.6B','cuda')]
    state={'index':-1,'done':False,'old':[],'raw':bytearray(),'releasing_since':0.};rows=[];events=[];problems=[]
    original_event=speech._event
    def receive(value):
        if value.get('event')=='speech_audio':state['raw'].extend(base64.b64decode(value['pcm']))
        original_event(value)
    speech._event=receive;speech.problem.connect(problems.append)
    def finish():
        if state['done']:return
        state['done']=True;timer.stop();speech.close()
        passed=len(rows)==len(cases) and not problems and all(row['released_previous'] and row.get('completed') for row in rows)
        state['passed']=passed
        result={'passed':passed,'cases':rows,'events':events,'problems':problems}
        (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'passed':passed,'cases':len(rows),'problems':problems}),flush=True);app.quit()
    def begin():
        if state['done']:return
        if state['index']+1==len(cases):finish();return
        old=[]
        if speech.process:
            try:old=[psutil.Process(speech.process.processId())];old+=old[0].children(recursive=True)
            except psutil.Error:pass
        state['index']+=1;state['old']=old;state['raw'].clear();state['releasing_since']=time.monotonic()
        size,device=cases[state['index']]
        speech.configure(SpeechConfig(True,device,LECTURE_VOICE,30,1.25,False,size))
        timer.start()
    def wait_release():
        alive=[p.pid for p in state['old'] if p.is_running()]
        if alive:
            if time.monotonic()-state['releasing_since']>8:problems.append('previous model worker remained alive');finish()
            return
        timer.stop();size,device=cases[state['index']]
        rows.append({'index':state['index'],'model_size':size,'device':device,'released_previous':True})
        speech.enqueue('请注意，这个矩阵必须是方阵。可惜，这里不适用。');speech._load();speech._next()
    def diagnostic(row):
        index=state['index'];events.append({'case':index,**row});print(json.dumps({'case':index,**row},ensure_ascii=False),flush=True)
        if row['event']=='speech_ready':
            rows[-1]['ready']=row
            if row['model_size']!=cases[index][0] or row['device']!=cases[index][1]:problems.append('model/device mismatch')
        elif row['event']=='speech_done':
            path=args.output/f'{index}-raw.wav'
            with wave.open(str(path),'wb') as writer:
                writer.setparams((1,2,24000,0,'NONE','not compressed'));writer.writeframes(state['raw'])
            rows[-1]['generation']=row
            rows[-1]['rendered']=render(path,args.output/f'{index}-1.25x.wav',1.25)
        elif row['event']=='speech_playback_finished':rows[-1]['completed']=True;QTimer.singleShot(100,begin)
    speech.diagnostic.connect(diagnostic)
    timer=QTimer();timer.setInterval(50);timer.timeout.connect(wait_release)
    QTimer.singleShot(0,begin);QTimer.singleShot(360000,finish)
    app.exec();return 0 if state.get('passed') else 2


if __name__=='__main__':raise SystemExit(main())
