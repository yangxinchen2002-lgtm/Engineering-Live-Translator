from app.i18n import tr as _tr
"""Restore source volume on STOP, pipe closure, or death of the owning GUI.

Intentionally outside the GUI's kill-on-close job: it must survive long enough
to restore volume if the GUI is terminated unexpectedly.
"""
import argparse
import json
import sys
import time


def emit(event,**values):
    try:print(json.dumps({'event':event,**values},ensure_ascii=False),flush=True)
    except OSError:pass  # The owning GUI may have died; restoration must still finish.


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--owner',type=int,required=True)
    args=parser.parse_args();sys.coinit_flags=0
    import msvcrt
    import win32api,win32event,win32file,win32pipe
    from app.audio.processes import ProcessInfo,ProcessSelector,process_source
    from app.audio.source_volume import SourceAttenuator,CoreAudioBackend
    owner=win32api.OpenProcess(0x100000,False,args.owner)
    stdin=msvcrt.get_osfhandle(sys.stdin.fileno());pending=b'';target=None;attenuator=None;mutex=None
    held=False;percent=20;state=None
    def report(value,**fields):
        nonlocal state
        signature=(value,tuple(fields.items()))
        if signature!=state:state=signature;emit(value,**fields)
    def release():
        nonlocal attenuator,held,mutex
        failed=attenuator.restore() if attenuator else 0;attenuator=None
        if held and mutex:win32event.ReleaseMutex(mutex)
        if mutex:mutex.Close()
        mutex=None;held=False
        if failed:emit('source_volume_restore_warning',sessions=failed)
    try:
        backend=CoreAudioBackend();selector=ProcessSelector()
        while win32event.WaitForSingleObject(owner,0)==win32event.WAIT_TIMEOUT:
            try:
                _,available,_=win32pipe.PeekNamedPipe(stdin,0)
                if available:
                    _,data=win32file.ReadFile(stdin,min(available,32768));pending+=data
            except Exception:break
            if len(pending)>32768:raise ValueError('volume command exceeds limit')
            while b'\n' in pending:
                line,pending=pending.split(b'\n',1);value=json.loads(line)
                if value.get('command')=='stop':release();emit('source_volume_restored');return 0
                if value.get('command')!='set':raise ValueError('invalid volume command')
                next_target=ProcessInfo(**value['target']);process_source(next_target)
                next_percent=value['percent']
                if type(next_percent) is not int or not 0<=next_percent<=100:raise ValueError('invalid volume level')
                if target!=next_target:
                    release();target=next_target
                    if selector.inspect(target.pid)!=target:raise ProcessLookupError('source changed')
                    mutex=win32event.CreateMutex(None,False,f'Local\\ELT.SourceVolume.{target.pid}.{target.created}')
                percent=next_percent
            if target:
                if not held:
                    held=win32event.WaitForSingleObject(mutex,0) in (win32event.WAIT_OBJECT_0,win32event.WAIT_ABANDONED)
                if held:
                    if attenuator is None:attenuator=SourceAttenuator(target,backend,selector)
                    count=attenuator.update(percent)
                    report('source_volume_applied' if count else 'source_volume_waiting',sessions=count,percent=percent)
                else:report('source_volume_busy')
            time.sleep(.25)
        release();emit('source_volume_restored');return 0
    except ProcessLookupError:
        release();emit('source_volume_source_ended');return 0
    except Exception:
        release();emit('source_volume_error',message=_tr('原声音量暂时无法自动调整，朗读和字幕继续。'));return 2
    finally:
        release();owner.Close()


if __name__=='__main__':raise SystemExit(main())
