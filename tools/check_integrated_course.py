"""Real public lecture -> existing ELT -> Chinese playback -> TXT -> automatic and manual AI notes."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from PySide6.QtCore import QTimer
from app.ui.window import MainWindow,STYLE
from app.audio.processes import ProcessSelector
from live_checks import Player


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--media',type=Path,default=ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4')
    parser.add_argument('--seconds',type=int,default=50)
    parser.add_argument('--single-summary',action='store_true')
    args=parser.parse_args()
    if not args.media.is_file():parser.error('course media must exist before starting')
    args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);app.setStyle('Fusion');app.setFont(QFont('Microsoft YaHei UI',10));app.setStyleSheet(STYLE)
    player=Player(ROOT/'tools/vlc-3.0.24/vlc.exe',args.media.resolve(),args.output/'vlc.txt',ready_timeout=60)
    player.command('pause');target=ProcessSelector().inspect(player.child.pid)
    window=MainWindow();window.show();controller=window.controller
    window.transcript_directory=args.output;window.transcript_folder_label.setText(str(args.output))
    events=[];speech=[];problems=[];saved=[];subtitles=[]
    started=time.monotonic();state={'started':False,'ready':None,'stop':False,'manual':False,'finished':False}
    last_tick=[started];gaps=[]
    log=(args.output/'events.jsonl').open('x',encoding='utf-8')
    def event(row):
        events.append(row);log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
        if row['event']=='audio_source_ready':
            state['ready']=time.monotonic();player.command('seek 0');player.command('pause')
    controller.event_received.connect(event)
    controller.subtitle_received.connect(lambda row:subtitles.append(dict(row)))
    def speech_event(row):
        speech.append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    window.speech.diagnostic.connect(speech_event)
    window.speech.problem.connect(problems.append);window.notes.problem.connect(problems.append)
    controller.problem.connect(problems.append)
    window.notes.saved.connect(lambda row:saved.append(dict(row)))
    window.notes.status_changed.connect(lambda message:print(message,flush=True))
    def tick():
        now=time.monotonic();gaps.append(now-last_tick[0]);last_tick[0]=now
        if not state['started'] and window.credential_status.get('available'):
            state['started']=True
            window.language.setCurrentIndex(window.language.findData('en'))
            window.translation_mode.setCurrentIndex(window.translation_mode.findData('sentence'))
            window.translate_check.setChecked(True);window.save_transcripts_check.setChecked(True)
            window.auto_summary_check.setChecked(True);window.speech_check.setChecked(True)
            window.process_combo.addItem('验收用公开课程 VLC',target);window.process_combo.setCurrentIndex(window.process_combo.count()-1)
            window.start_button.click()
        if state['ready'] and now-state['ready']>args.seconds and not state['stop']:
            state['stop']=True;window.grab().save(str(args.output/'live-translating.png'))
            window.stop_button.click()
        if saved and not args.single_summary and not window.notes.busy and not controller.running and not state['manual']:
            state['manual']=True;window.summary_button.click()
        if len(saved)==(1 if args.single_summary else 2) and not window.notes.busy:finish()
        elif now-started>300:finish()
    def finish():
        if state['finished']:return
        state['finished']=True;timer.stop()
        final={r['segment_id']:r for r in subtitles if r.get('state')=='final' and r.get('translated_text')}
        result={'passed':False,'elapsed_seconds':time.monotonic()-started,'credential_available':bool(window.credential_status.get('available')),
                'capture_started':state['started'],'audio_ready':bool(state['ready']),
                'forced_stop':controller.forced,'problems':problems,'translated_segments':len(final),
                'playback_finished':sum(row['event']=='speech_playback_finished' for row in speech),
                'speech_events':speech,'ai_outputs':saved,'transcript_path':str(window.last_transcript_path or ''),
                'full_course_records':len(controller.course.snapshot()['records']),
                'max_event_loop_gap_seconds':max(gaps,default=0),
                'translation_summary':next((r for r in reversed(events) if r['event']=='bilingual_summary'),{})}
        result['passed']=bool(state['stop'] and not controller.running and not controller.forced and not problems and final
                              and result['playback_finished'] and len(saved)==(1 if args.single_summary else 2)
                              and len({r['path'] for r in saved})==len(saved)
                              and all(Path(r['path']).is_file() for r in saved) and window.last_transcript_path and window.last_transcript_path.is_file())
        window.settings_tabs.setCurrentWidget(window.settings_scroll)
        window.settings_scroll.ensureWidgetVisible(window.summary_button);app.processEvents()
        window.grab().save(str(args.output/'completed-with-ai-notes.png'))
        (args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k not in ('speech_events','translation_summary','ai_outputs')},ensure_ascii=False),flush=True)
        if controller.running:controller.force_stop()
        window.notes.close();window.close();app.quit()
    timer=QTimer();timer.setInterval(100);timer.timeout.connect(tick);timer.start()
    try:app.exec()
    finally:
        player.close();log.close();window.notes.close();window.speech.close()
        if controller.running:controller.force_stop()
        controller.cleanup_idle()
    result=json.loads((args.output/'results.json').read_text(encoding='utf-8'))
    return 0 if result['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
