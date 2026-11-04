"""Real GUI/controller/native/GPU checks; Qt business API, no synthetic subtitles or cloud."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from app.ui.window import MainWindow,STYLE
from app.audio.processes import ProcessSelector
from live_checks import Player
from live_m1_checks import children_of


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    player=Player(ROOT/'tools/vlc-3.0.24/vlc.exe',ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4',args.output/'vlc.txt')
    player.command('pause');target=ProcessSelector().inspect(player.child.pid)
    window=MainWindow();window.setWindowTitle('ELT · 实机验收');window.language.setCurrentIndex(1)
    window.font_value.setValue(12);window.sentence_spin.setValue(6)
    window.show();window.overlay_check.setChecked(True);controller=window.controller
    output=(args.output/'events.jsonl').open('x',encoding='utf-8')
    results={};events=[];snapshots=[];case=[1];ready=[None];last_tick=[time.monotonic()];gaps=[];stop_requested=[None]
    pause_done=[False];resume_done=[False];child_pids=set();started=[time.monotonic()]
    resume_at=[None];after_resume=[0];max_rows=[0]
    def event(row):
        events.append(row);output.write(json.dumps(row,ensure_ascii=False)+'\n');output.flush()
        if row['event']=='audio_source_ready':
            ready[0]=time.monotonic();player.command('seek 0');player.command('pause')
        if row['event']=='asr_worker_started':child_pids.add(row['pid'])
    controller.event_received.connect(event)
    def render():
        record=controller.model.current
        if record and (record['source_text'] or record['candidate_text']):
            snapshots.append(dict(record));max_rows[0]=max(max_rows[0],len(window.overlay.rows))
            if resume_at[0] and time.monotonic()>resume_at[0]+1.5:after_resume[0]+=1
    controller.view_changed.connect(render)
    def tick():
        now=time.monotonic();gaps.append(now-last_tick[0]);last_tick[0]=now
        if now-started[0]>160:
            results['timeout']=True;controller.force_stop();QTimer.singleShot(1500,app.quit);return
        if controller.backend_pid:
            child_pids.update(pid for pid,name in children_of(controller.backend_pid))
        if case[0]==1 and ready[0]:
            elapsed=now-ready[0]
            if elapsed>18 and not pause_done[0]:player.command('pause');pause_done[0]=True
            if elapsed>21 and not resume_done[0]:
                player.command('pause');resume_done[0]=True;resume_at[0]=now
            if elapsed>35 and not controller.stopping:
                stop_requested[0]=time.monotonic();controller.stop()
    timer=QTimer();timer.setInterval(100);timer.timeout.connect(tick);timer.start()
    def done(code,requested):
        if case[0]==1:
            summary=next((r for r in reversed(events) if r['event']=='bilingual_summary'),{})
            results['live_source_only']={'exit_code':code,'requested_stop':requested,'forced':controller.forced,
                'stop_seconds':time.monotonic()-stop_requested[0] if stop_requested[0] else None,
                'real_subtitle_updates':len(snapshots),'sample_source':snapshots[-1]['source_text'] if snapshots else '',
                'fake_chinese_events':sum(bool(r['translated_text']) for r in snapshots),
                'api_attempts':summary.get('translation_attempts'),'pause_resume_requested':pause_done[0] and resume_done[0],
                'updates_after_resume':after_resume[0],'max_visible_subtitle_rows':max_rows[0],
                'performance':controller.telemetry.snapshot(),
                'max_event_loop_gap_seconds':max(gaps),'worker_and_helper_pids':sorted(child_pids)}
            results['live_source_only']['verified']=(requested and not controller.forced and code==130 and bool(snapshots)
                and summary.get('translation_attempts')==0 and not any(r['translated_text'] for r in snapshots)
                and pause_done[0] and resume_done[0] and after_resume[0]>0 and max_rows[0]>=2
                and bool(controller.telemetry.series.get('ui_delivery_overlay')))
            case[0]=2;events.clear();ready[0]=None
            def again():
                controller.start(target,'en',False,60)
                QTimer.singleShot(200,lambda:(stop_requested.__setitem__(0,time.monotonic()),controller.stop()))
            QTimer.singleShot(200,again)
        else:
            results['cancel_loading']={'exit_code':code,'requested_stop':requested,'forced':controller.forced,
                'stop_seconds':time.monotonic()-stop_requested[0],
                'verified':requested and not controller.forced and code==130}
            timer.stop();window.close();app.quit()
        (args.output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    controller.finished.connect(done)
    QTimer.singleShot(600,lambda:controller.start(target,'en',False,60))
    try:app.exec()
    finally:
        player.close();output.close()
        if controller.running:controller.force_stop()
        controller.cleanup_idle()
    return 0 if len(results)==2 and all(r.get('verified') for r in results.values()) else 2


if __name__=='__main__':raise SystemExit(main())
