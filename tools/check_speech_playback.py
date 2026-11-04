"""Actual Qt audio output and GUI device switching; requires the installed local models."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from app.ui.window import MainWindow,STYLE


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    window=MainWindow();window.show();window.settings_tabs.setCurrentWidget(window.speech_scroll)
    events=[];problems=[];state={'phase':'cuda','complete':False};started=time.monotonic()
    window.speech.problem.connect(problems.append)
    window.speech.status_changed.connect(lambda message:print(message,flush=True))
    def diagnostic(row):
        events.append({'phase':state['phase'],**row})
        print(json.dumps({'phase':state['phase'],**row}),flush=True)
        if row['event']=='speech_playback_finished':
            if state['phase']=='cuda':
                state['phase']='cpu'
                window.speech_device.setCurrentIndex(window.speech_device.findData('cpu'))
                window.speech_voice.setCurrentIndex(window.speech_voice.findData('uncle_fu'))
                QTimer.singleShot(300,play)
            else:
                state['complete']=True
                window.grab().save(str(args.output/'cpu-playback.png'))
                QTimer.singleShot(200,finish)
    window.speech.diagnostic.connect(diagnostic)
    def play():
        speech=window.speech
        speech.paused=False;speech.enqueue('你好，这是中文朗读测试。')
        speech._load();speech._next()
    def finish():
        result={'passed':state['complete'] and not problems,'events':events,'problems':problems,
                'elapsed_seconds':time.monotonic()-started}
        (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        window.close();app.quit()
    def debug():
        speech=window.speech
        if speech.sink:
            print(json.dumps({'audio_state':str(speech.sink.state()),'audio_error':str(speech.sink.error()),
                              'processed_us':speech.sink.processedUSecs(),'expected_us':speech.samples/speech.rate*1e6,
                              'pcm_bytes':speech.pcm_bytes,'done':speech.audio_done}),flush=True)
    timer=QTimer();timer.setInterval(5000);timer.timeout.connect(debug);timer.start()
    QTimer.singleShot(1000,play);QTimer.singleShot(300000,finish)
    app.exec()
    return 0 if state['complete'] and not problems else 2


if __name__=='__main__':raise SystemExit(main())
