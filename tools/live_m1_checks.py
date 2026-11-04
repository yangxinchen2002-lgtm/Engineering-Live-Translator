"""Real VLC -> native -> Python -> GPU checks. Starts audible public lectures.

Run after benchmarks to avoid competing for GPU. New explicit output directory required.
Only this tool's VLC instances and CLI children are controlled/closed.
"""
import argparse
import ctypes as ct
from ctypes import wintypes as wt
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from live_checks import Player
from app.audio.processes import ProcessSelector
from app.asr.course_terms import CourseTerms


def children_of(pid):
    selector=ProcessSelector();k=selector.k32
    snapshot=k.CreateToolhelp32Snapshot(2,0)
    if snapshot==ct.c_void_p(-1).value:raise ct.WinError(ct.get_last_error())
    rows=[]
    try:
        e=selector.Entry();e.dwSize=ct.sizeof(e)
        ok=k.Process32FirstW(snapshot,ct.byref(e))
        while ok:
            if e.th32ParentProcessID==pid:rows.append((e.th32ProcessID,e.szExeFile))
            ok=k.Process32NextW(snapshot,ct.byref(e))
    finally:k.CloseHandle(snapshot)
    return rows


def parent_of(pid):
    selector=ProcessSelector();k=selector.k32
    snapshot=k.CreateToolhelp32Snapshot(2,0)
    if snapshot==ct.c_void_p(-1).value:raise ct.WinError(ct.get_last_error())
    try:
        e=selector.Entry();e.dwSize=ct.sizeof(e)
        ok=k.Process32FirstW(snapshot,ct.byref(e))
        while ok:
            if e.th32ProcessID==pid:return e.th32ParentProcessID
            ok=k.Process32NextW(snapshot,ct.byref(e))
        raise RuntimeError('worker no longer exists')
    finally:k.CloseHandle(snapshot)


class LiveRun:
    def __init__(self,output,name,player,language,seconds,course_terms=None):
        self.log=output/(name+'.jsonl')
        self.stdout=(output/(name+'.stdout.txt')).open('xb')
        self.stderr=(output/(name+'.stderr.txt')).open('xb')
        command=[sys.executable,'-X','utf8','-m','app.main','asr-live','--pid',str(player.child.pid),
                 '--language',language,'--seconds',str(seconds),'--log',str(self.log)]
        if course_terms:command.extend(['--course-terms',str(course_terms.resolve())])
        self.child=subprocess.Popen(command,cwd=ROOT,stdout=self.stdout,stderr=self.stderr,
            creationflags=subprocess.CREATE_NO_WINDOW)

    def rows(self):
        if not self.log.exists():return []
        data=self.log.read_bytes()
        complete=data.rsplit(b'\n',1)[0] if b'\n' in data else b''
        return [json.loads(line) for line in complete.decode('utf-8').splitlines() if line.strip()]

    def ready(self):
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            if any(r['event']=='asr_model_ready' for r in self.rows()):return
            if self.child.poll() is not None:raise RuntimeError(f'live ASR startup failed: {self.rows()[-2:]}')
            time.sleep(.1)
        raise TimeoutError('live model startup did not complete')

    def finish(self,timeout=100):
        try:code=self.child.wait(timeout=timeout)
        finally:
            if self.child.poll() is None:self.child.terminate();self.child.wait(timeout=5)
            self.stdout.close();self.stderr.close()
        rows=self.rows()
        return {'exit_code':code,'summaries':[r for r in rows if r['event']=='asr_summary'],
                'errors':[r for r in rows if r['event']=='asr_error'],
                'worker_pids':[r['pid'] for r in rows if r['event']=='asr_worker_started'],
                'transcript_events':sum(r['event']=='transcript' for r in rows)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seconds',type=int,default=60)
    p.add_argument('--include-auto',action='store_true')
    p.add_argument('--languages',nargs='+',choices=['de','en','auto'],default=['de','en'])
    p.add_argument('--auto-sample',choices=['de','en'],default='de')
    p.add_argument('--failures',action='store_true')
    p.add_argument('--course-terms',type=Path,help='optional vocabulary matching the selected course language')
    a=p.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    course=CourseTerms.load(a.course_terms) if a.course_terms else None
    if course and any(lang not in ('auto',course.language) for lang in a.languages):
        p.error('select only the fixed language matching --course-terms, or auto')
    results={};vlc=ROOT/'tools/vlc-3.0.24/vlc.exe'
    for lang in a.languages+(['auto'] if a.include_auto and 'auto' not in a.languages else []):
        source_language=a.auto_sample if lang=='auto' else lang
        media=ROOT/('tests/fixtures/public-m1/en-linear-algebra.mp4' if source_language=='en' else 'tests/fixtures/public-m1/de-open-source-firmware.mp3')
        player=Player(vlc,media,a.output/('vlc-'+lang+'.txt'))
        player.command('pause')
        try:
            run=LiveRun(a.output,lang,player,lang,a.seconds,a.course_terms)
            run.ready();time.sleep(.3);player.command('seek 0');player.command('pause')
            if a.seconds>=45:
                time.sleep(28);player.command('pause');pause_ns=time.perf_counter_ns()
                time.sleep(3);player.command('pause');resume_ns=time.perf_counter_ns()
            else:pause_ns=resume_ns=None
            result=run.finish(a.seconds+30)
            result.update(pause_requested_ns=pause_ns,resume_requested_ns=resume_ns)
            result['verified']=result['exit_code']==0 and bool(result['summaries']) and result['summaries'][-1]['committed_word_count']>0
            result['negative_clock_errors']=[r for r in run.rows() if r['event']=='transcript' and
                                              r.get('latency_seconds') is not None and r['latency_seconds'] < -.1]
            result['verified'] &= not result['negative_clock_errors']
            if lang=='auto':result['verified'] &= result['summaries'][-1]['locked_language']==source_language
            if course:
                result['course_terms_applied_jobs']=result['summaries'][-1]['course_terms_jobs']
                result['verified'] &= result['course_terms_applied_jobs']>0
            results[lang]=result;print(json.dumps({lang:result}),flush=True)
        finally:player.close()
    if a.failures:
        for name in ['target_exit','hard_parent_kill']:
            failure_language=course.language if course else 'de'
            failure_media=ROOT/('tests/fixtures/public-m1/en-linear-algebra.mp4' if failure_language=='en'
                               else 'tests/fixtures/public-m1/de-open-source-firmware.mp3')
            player=Player(vlc,failure_media,a.output/('vlc-'+name+'.txt'))
            player.command('pause')
            try:
                run=LiveRun(a.output,name,player,failure_language,60,a.course_terms);run.ready()
                player.command('seek 0');player.command('pause');time.sleep(3)
                if name=='target_exit':
                    started=time.monotonic();player.close();result=run.finish(25)
                    result['cleanup_seconds']=time.monotonic()-started
                    result['verified']=result['exit_code']!=0 and any('target_exited' in str(e) for e in result['errors'])
                else:
                    import win32api,win32event
                    worker_pid=next(r['pid'] for r in run.rows() if r['event']=='asr_worker_started')
                    actual_parent=parent_of(worker_pid)
                    children=children_of(actual_parent)
                    watched=[(pid,win32api.OpenProcess(0x100000|0x1000,False,pid)) for pid,_ in children]
                    parent=win32api.OpenProcess(1|0x100000,False,actual_parent)
                    started=time.monotonic()
                    try:
                        win32api.TerminateProcess(parent,99)
                        exited={str(pid):win32event.WaitForSingleObject(handle,8000)==0 for pid,handle in watched}
                        result=run.finish(15);result.update(child_exit_confirmed=exited,cleanup_seconds=time.monotonic()-started,
                                                          actual_parent_pid=actual_parent,verified=all(exited.values()) and bool(exited))
                    finally:
                        parent.Close()
                        for _,handle in watched:handle.Close()
                results[name]=result;print(json.dumps({name:result}),flush=True)
            finally:player.close()
    (a.output/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    return 0 if all(r['verified'] for r in results.values()) else 2


if __name__=='__main__':raise SystemExit(main())
