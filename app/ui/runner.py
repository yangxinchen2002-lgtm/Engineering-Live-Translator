"""Private real backend entry point with bounded stdin STOP control; no Qt imports."""
from __future__ import annotations
import _thread
import json
import os
import sys
import threading
from .lifetime import JOB_ENV,join_owner_job


def control(stop:threading.Event,pause:threading.Event):
    import msvcrt,win32file,win32pipe
    handle=msvcrt.get_osfhandle(sys.stdin.fileno())
    buffer=b''
    while not stop.wait(.05):
        try:
            _,available,_=win32pipe.PeekNamedPipe(handle,0)
            if not available:continue
            _,data=win32file.ReadFile(handle,min(available,4096))
        except Exception:
            if not stop.is_set():_thread.interrupt_main()
            return
        buffer+=data
        if len(buffer)>4096:
            _thread.interrupt_main();return
        while b'\n' in buffer:
            line,buffer=buffer.split(b'\n',1)
            if line.strip()==b'STOP':
                _thread.interrupt_main();return
            if line.strip()==b'PAUSE':pause.set()
            elif line.strip()==b'RESUME':pause.clear()


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    try:join_owner_job(os.environ.get(JOB_ENV,''))
    except Exception:
        print(json.dumps({'event':'gui_backend_error','code':'lifecycle_attach_failed'}),flush=True);return 1
    print(json.dumps({'event':'gui_backend_started','pid':os.getpid(),'lifecycle_protected':True}),flush=True)
    stop=threading.Event();pause=threading.Event()
    thread=threading.Thread(target=control,args=(stop,pause),name='ELT-GUI-Control',daemon=True)
    thread.start()
    try:
        from app.main import main as cli_main
        return cli_main(sys.argv[1:],pause_event=pause)
    except KeyboardInterrupt:
        print(json.dumps({'event':'bilingual_cancelled','complete':False}),flush=True);return 130
    finally:
        stop.set();thread.join(timeout=1)


if __name__=='__main__':raise SystemExit(main())
