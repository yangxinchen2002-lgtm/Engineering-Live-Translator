"""No-key real VLC/native/GPU M2 degradation checks; no cloud requests or fake Chinese."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from live_checks import Player
from live_m1_checks import children_of,parent_of
from app.translation.credentials import read_credential


class Run:
    def __init__(self,output,name,player,seconds=60):
        self.log=output/(name+'.jsonl')
        self.stdout=(output/(name+'.stdout.txt')).open('xb')
        self.stderr=(output/(name+'.stderr.txt')).open('xb')
        self.child=subprocess.Popen([sys.executable,'-X','utf8','-m','app.main','translate-live',
            '--pid',str(player.child.pid),'--language','en','--seconds',str(seconds),
            '--log',str(self.log),'--history',str(output/(name+'.history.jsonl'))],cwd=ROOT,
            stdout=self.stdout,stderr=self.stderr,creationflags=subprocess.CREATE_NO_WINDOW)

    def rows(self):
        if not self.log.exists():return []
        data=self.log.read_bytes()
        complete=data.rsplit(b'\n',1)[0] if b'\n' in data else b''
        return [json.loads(line) for line in complete.decode('utf-8').splitlines() if line.strip()]

    def wait_event(self,event,timeout=100):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            rows=self.rows()
            if any(r['event']=='translation_credentials' and r['available'] for r in rows):
                raise RuntimeError('no-key test refused: credentials became available')
            found=[r for r in rows if r['event']==event]
            if found:return found[-1]
            if self.child.poll() is not None:raise RuntimeError(f'{event} not reached; exit={self.child.returncode}')
            time.sleep(.02)
        raise TimeoutError(f'{event} deadline')

    def finish(self,timeout=100):
        try:code=self.child.wait(timeout=timeout)
        finally:
            if self.child.poll() is None:self.child.terminate();self.child.wait(timeout=10)
            self.stdout.close();self.stderr.close()
        rows=self.rows()
        return {'exit_code':code,'asr_summary':[r for r in rows if r['event']=='asr_summary'],
                'bilingual_summary':[r for r in rows if r['event']=='bilingual_summary'],
                'errors':[r for r in rows if r['event'] in ('bilingual_error','asr_error')],
                'worker_pids':[r['pid'] for r in rows if r['event']=='asr_worker_started'],
                'subtitle_events':sum(r['event']=='subtitle' for r in rows),
                'translated_events':sum(r['event']=='subtitle' and bool(r['translated_text']) for r in rows),
                'final_events':sum(r['event']=='subtitle' and r['state']=='final' for r in rows)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output=a.output.resolve()
    if read_credential() is not None:p.error('this test requires no configured key; credentials are not modified')
    a.output.mkdir(parents=True,exist_ok=False)
    results={}
    for name in ('no_key_pause_resume','target_exit_inflight','parent_kill_inflight'):
        player=Player(ROOT/'tools/vlc-3.0.24/vlc.exe',ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4',
                      a.output/('vlc-'+name+'.txt'))
        player.command('pause');run=None
        try:
            run=Run(a.output,name,player)
            run.wait_event('asr_model_ready');player.command('seek 0');player.command('pause')
            if name=='no_key_pause_resume':
                time.sleep(28);player.command('pause');pause=time.perf_counter_ns()
                time.sleep(3);player.command('pause');resumed=time.perf_counter_ns()
                result=run.finish(90)
                summary=result['bilingual_summary'][-1] if result['bilingual_summary'] else {}
                after=[r for r in run.rows() if r['event']=='subtitle' and r['monotonic_ns']>resumed+2_000_000_000]
                result.update(pause_ns=pause,resume_ns=resumed,subtitles_after_resume=len(after))
                result['verified']=(result['exit_code']==3 and summary.get('asr_complete') is True
                    and summary.get('translation_available') is False and summary.get('translation_attempts')==0
                    and summary.get('translation_complete') is False and result['subtitle_events']>0 and bool(after)
                    and result['translated_events']==0 and result['final_events']==0 and not result['errors'])
            else:
                submitted=run.wait_event('asr_submitted',timeout=45)
                started=time.perf_counter_ns()
                if name=='target_exit_inflight':
                    player.close();result=run.finish(30)
                    result['verified']=result['exit_code']==1 and bool(result['errors']) and result['bilingual_summary'][-1]['asr_complete'] is False
                else:
                    import win32api,win32event
                    parent_pid=parent_of(submitted['worker_pid'])
                    watched=[(pid,win32api.OpenProcess(0x100000|0x1000,False,pid)) for pid,_ in children_of(parent_pid)]
                    parent=win32api.OpenProcess(1|0x100000,False,parent_pid)
                    try:
                        win32api.TerminateProcess(parent,99)
                        exited={str(pid):win32event.WaitForSingleObject(handle,8000)==0 for pid,handle in watched}
                        result=run.finish(15)
                        result.update(actual_parent_pid=parent_pid,child_exit_confirmed=exited)
                        result['verified']=bool(exited) and all(exited.values())
                    finally:
                        parent.Close()
                        for _,handle in watched:handle.Close()
                result['cleanup_seconds']=(time.perf_counter_ns()-started)/1e9
                result['submitted_to_action_seconds']=(started-submitted['submitted_ns'])/1e9
            results[name]=result
            (a.output/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
            print(json.dumps({name:result}),flush=True)
        finally:
            player.close()
            if run and run.child.poll() is None:
                run.child.terminate();run.child.wait(timeout=10);run.stdout.close();run.stderr.close()
    return 0 if all(r['verified'] for r in results.values()) else 2


if __name__=='__main__':raise SystemExit(main())
