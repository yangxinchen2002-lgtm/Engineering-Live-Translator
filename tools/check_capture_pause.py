"""Short real Windows process-loopback pause check; plays a quiet owned test tone.

No ASR/TTS model, cloud call, user app control or saved PCM. The same production
LiveSource is used. A helper is observed only through this tool's child processes.
"""
import argparse
import json
from pathlib import Path
import queue
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run(output):
    import numpy as np
    import psutil
    from app.asr.source import LiveSource
    from app.audio.processes import ProcessSelector
    if output.exists():raise FileExistsError('choose a new report path')
    report={'passed':False,'real_loopback':True,'models_loaded':False,'api_requests':0,'cycles':[]}
    player=source=None;frames=[];transitions=[];helper_pids=set()
    def helper_children():
        return [p for p in psutil.Process().children() if p.name().casefold()=='elt_capture.exe']
    def pump_until(condition,timeout=8):
        deadline=time.monotonic()+timeout
        while True:
            if source.error:raise RuntimeError(str(source.error))
            while True:
                try:frames.append(source.queue.get_nowait())
                except queue.Empty:break
            while True:
                try:transitions.append(source.pause_events.get_nowait())
                except queue.Empty:break
            helper_pids.update(p.pid for p in helper_children())
            if condition():return
            if time.monotonic()>deadline:raise TimeoutError('short check condition not met')
            time.sleep(.01)
    try:
        player=subprocess.Popen([sys.executable,'-B','-u','-X','utf8',str(ROOT/'tools/check_application_audio.py'),'--tone','1000'],
            cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=subprocess.CREATE_NO_WINDOW)
        import threading
        ready=queue.Queue(maxsize=1)
        threading.Thread(target=lambda:ready.put(player.stdout.readline()),daemon=True).start()
        info=json.loads(ready.get(timeout=12))
        if info['event']!='ready':raise RuntimeError('test player did not start')
        target=ProcessSelector().inspect(info['pid'])
        source=LiveSource(ROOT/'native/build/Release/elt_capture.exe',target,22,200,lambda *a,**k:None)
        source.start();pump_until(lambda:source.ready.is_set() and len(frames)>=30)
        for _ in range(3):
            before=len(frames);source.pause_event.set()
            pump_until(lambda:transitions and transitions[-1]['paused'])
            paused=transitions[-1];count=len(frames);until=time.monotonic()+.35
            pump_until(lambda:time.monotonic()>=until)
            no_new_audio=len(frames)==count;no_helper=not helper_children();at=time.monotonic()
            source.pause_event.clear()
            pump_until(lambda:not transitions[-1]['paused'] and len(frames)>=count+15)
            report['cycles'].append({'sample':paused['sample'],'no_audio_while_paused':no_new_audio,
                'helper_reaped_while_paused':no_helper,'same_sample_on_resume':transitions[-1]['sample']==paused['sample'],
                'resume_to_15_frames_seconds':time.monotonic()-at,'frames_before_pause':count-before})
        source.pause_event.set();pump_until(lambda:transitions[-1]['paused'])
        source.close();report['stop_while_paused_clean']=source.done.is_set() and source.error is None and not helper_children()
        report['sample_axis_contiguous']=all(a.end==b.start for a,b in zip(frames,frames[1:]))
        report['wall_clock_gap_preserved']=any((b.end_ns-a.end_ns)/1e9>.3 for a,b in zip(frames,frames[1:]))
        report['nonzero_audio']=bool(frames) and max(float(np.max(np.abs(f.audio))) for f in frames)>1e-4
        report['unique_helpers']=len(helper_pids);report['audio_seconds']=sum(len(f.audio) for f in frames)/16000
        # Separate real exit during a pause; no resumed helper may bind a new PID.
        source=LiveSource(ROOT/'native/build/Release/elt_capture.exe',target,5,200,lambda *a,**k:None)
        source.pause_event.set();source.start();source.pause_events.get(timeout=2)
        player.stdin.write(b'stop\n');player.stdin.flush();player.wait(timeout=3)
        source.done.wait(3);report['target_exit_during_pause_reported']='target_exited' in str(source.error)
        source.close()
        report['passed']=all(report[key] for key in ('stop_while_paused_clean','sample_axis_contiguous',
            'wall_clock_gap_preserved','nonzero_audio','target_exit_during_pause_reported')) and all(
            all(cycle[key] for key in ('no_audio_while_paused','helper_reaped_while_paused','same_sample_on_resume')) for cycle in report['cycles'])
    except Exception as error:report['error']=str(error)
    finally:
        if source:
            try:source.close()
            except Exception as error:report['cleanup_error']=str(error);report['passed']=False
        if player:
            if player.poll() is None:
                try:player.stdin.write(b'stop\n');player.stdin.flush();player.wait(timeout=3)
                except (OSError,ValueError,subprocess.TimeoutExpired):player.kill();player.wait(timeout=3)
            for stream in (player.stdin,player.stdout,player.stderr):stream.close()
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if report['passed'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    raise SystemExit(run(parser.parse_args().output))
