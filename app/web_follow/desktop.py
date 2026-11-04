"""GUI-owned web service: bounded stdin controls and ordinary ELT subtitle events."""
from __future__ import annotations
from app.i18n import tr as _tr
import asyncio
import json
import os
from pathlib import Path
import queue
import secrets
import sys
import threading
import time

from app.ui.lifetime import JOB_ENV,join_owner_job
from app.subtitles.transcript import TranscriptWriter
from .server import Lab,Server,options_from,READING_FIELDS
from .presentation import Presentation


def emit(event,**data):
    print(json.dumps(dict(event=event,**data),ensure_ascii=False,allow_nan=False),flush=True)


def configuration(raw):
    if not raw.startswith(b'CONFIG ') or not raw.endswith(b'\n') or len(raw)>32768:raise ValueError(_tr('网页模式启动配置无效'))
    data=json.loads(raw[7:])
    # Playback fields are shared with the live settings API, so new validated
    # appearance controls cannot be rejected only at the process boundary.
    allowed={'language','provider','model','translate','lookahead','glossary',
             'seconds','transcript_directory','tts_device','target_language','ui_language'}|READING_FIELDS
    if not isinstance(data,dict) or data.keys()-allowed:raise ValueError(_tr('网页模式启动配置包含未知字段'))
    options=options_from(data);seconds=data.get('seconds',3600)
    if type(seconds) is not int or not 1<=seconds<=28800:raise ValueError(_tr('网页模式运行时长无效'))
    directory=data.get('transcript_directory')
    if directory is not None and (not isinstance(directory,str) or len(directory)>4096 or '\x00' in directory
                                  or not Path(directory).is_dir()):raise ValueError(_tr('翻译稿保存文件夹不可用'))
    return options,seconds,Path(directory) if directory else None


def control(stop,commands):
    import msvcrt,win32file,win32pipe
    handle=msvcrt.get_osfhandle(sys.stdin.fileno());buffer=b''
    while not stop.wait(.05):
        try:
            _,available,_=win32pipe.PeekNamedPipe(handle,0)
            if not available:continue
            _,chunk=win32file.ReadFile(handle,min(available,4096))
            buffer+=chunk
            if len(buffer)>4096:commands.put_nowait('STOP');return
            while b'\n' in buffer:
                line,buffer=buffer.split(b'\n',1)
                if line.strip()==b'STOP':commands.put_nowait('STOP');return
        except Exception:
            try:commands.put_nowait('STOP')
            except queue.Full:pass
            return


async def run(options,seconds,directory,commands):
    from app.i18n import set_language
    set_language(options.get('ui_language','zh'))
    lab=Lab();server=Server(lab,desktop_options=options)
    server_thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.2},daemon=True)
    server_thread.start();session=secrets.token_hex(16);view=Presentation(session,options)
    writer=TranscriptWriter(directory,session,'auto',emit,target_language=options.get('target_language','zh'));writer.start()
    emit('asr_session',realtime=False,mode='web-follow')
    emit('web_service_ready',url=server.origin+'/#'+server.token)
    emit('translation_status',mode='sentence')
    deadline=None;last_state=None;accounting=None
    try:
        while commands.empty():
            with lab.lock:lab.last_seen=time.monotonic()
            state=lab.state();state['paired']=server.bridge.status()['paired'];last_state=state
            if state['has_source']:
                if deadline is None:deadline=time.monotonic()+seconds
                writer.source_started();writer.capture_pause(state['paused'])
            for row in view.update(state):
                if row['event']=='subtitle' and row.get('source_closed'):writer.offer(row)
                if row['event']=='translation_usage':accounting=row
                emit(**row)
            if deadline is not None and time.monotonic()>=deadline:break
            await asyncio.sleep(.25)
    finally:
        server.desktop_stopping=True
        await asyncio.to_thread(lab.stop)
        final_usage=view.usage.update(view.usage.pid,lab.metrics)
        if final_usage:emit(**final_usage);accounting=final_usage
        await asyncio.sleep(.6)  # Let active pages receive the explicit stopped flag.
        writer.source_ended()
        complete=bool(last_state and last_state.get('duration') and last_state['position']>=last_state['duration']-.3
                      and not view.incomplete)
        try:
            stats=await writer.close(source_complete=complete)
            emit('bilingual_summary',asr_complete=complete,**{k:v for k,v in (accounting or {}).items() if k!='event'},**stats)
        finally:
            await asyncio.to_thread(server.shutdown);server.server_close();lab.close()
    return 0


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    stopped=threading.Event();commands=queue.Queue(maxsize=8);thread=None
    try:
        join_owner_job(os.environ.get(JOB_ENV,''))
        emit('gui_backend_started',pid=os.getpid(),lifecycle_protected=True)
        options,seconds,directory=configuration(sys.stdin.buffer.readline(32769))
        thread=threading.Thread(target=control,args=(stopped,commands),daemon=True,name='ELT-Web-Control');thread.start()
        return asyncio.run(run(options,seconds,directory,commands))
    except Exception as error:
        emit('gui_backend_error',code='web_follow_failed',message=str(error) if type(error) is ValueError else type(error).__name__)
        return 1
    finally:
        stopped.set()
        if thread:thread.join(timeout=1)


if __name__=='__main__':raise SystemExit(main())
