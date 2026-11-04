"""Real local worker -> lecture pause compaction -> Qt sound output, without capture."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model-size',choices=['0.6B','1.7B'],default='0.6B')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from app.ui.speech import SpeechController
    from app.speech.config import SpeechConfig,LECTURE_VOICE
    app=QApplication([]);speech=SpeechController()
    speech.configure(SpeechConfig(True,'cuda',LECTURE_VOICE,80,1.25,False,args.model_size))
    events=[];problems=[];state={'completed':False,'compactor_used':False,'removed_samples':0};start=time.monotonic()
    speech.problem.connect(problems.append)
    def finish():
        timer.stop();speech.close()
        passed=state['completed'] and state['compactor_used'] and not problems
        (args.output/'results.json').write_text(json.dumps({'passed':passed,**state,'events':events,
            'problems':problems,'elapsed_seconds':time.monotonic()-start},ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'passed':passed,**state,'problems':problems}),flush=True);app.quit()
    def event(row):
        events.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
        if row['event']=='speech_playback_finished':state['completed']=True;QTimer.singleShot(100,finish)
    def inspect():
        if speech.converter and speech.converter.pause_compactor:
            state['compactor_used']=True
            state['removed_samples']=max(state['removed_samples'],speech.converter.pause_compactor.removed_samples)
    speech.diagnostic.connect(event)
    timer=QTimer();timer.setInterval(50);timer.timeout.connect(inspect);timer.start()
    QTimer.singleShot(0,speech.preview);QTimer.singleShot(180000,finish)
    app.exec()
    return 0 if state['completed'] and state['compactor_used'] and not problems else 2


if __name__=='__main__':raise SystemExit(main())
