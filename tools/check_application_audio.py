"""Explicit two-app tone check of mixer discovery and genuine process loopback.

Runs short quiet test tones; never loads ASR/TTS models or a cloud client.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def tone_worker(frequency):
    import numpy as np
    from PySide6.QtCore import QCoreApplication,QTimer
    from PySide6.QtMultimedia import QAudioFormat,QAudioSink,QMediaDevices
    app=QCoreApplication([]);app.setApplicationName(f'ELT test {frequency} Hz')
    device=QMediaDevices.defaultAudioOutput()
    if device.isNull():raise RuntimeError('no default audio output')
    fmt=device.preferredFormat();rate=fmt.sampleRate();channels=fmt.channelCount()
    wave=np.sin(2*np.pi*frequency*np.arange(rate)/rate)*.08
    values=np.repeat(wave[:,None],channels,axis=1)
    kinds={QAudioFormat.Int16:('<i2',32767),QAudioFormat.Int32:('<i4',2147483647),
           QAudioFormat.Float:('<f4',1),QAudioFormat.UInt8:('u1',127)}
    dtype,scale=kinds[fmt.sampleFormat()]
    pcm=((values*scale)+ (128 if dtype=='u1' else 0)).astype(dtype).tobytes()
    sink=QAudioSink(device,fmt);sink.setVolume(.15);sink.setBufferSize(rate*fmt.bytesPerFrame()//4)
    output=sink.start()
    if output is None:raise RuntimeError('test audio output failed')
    commands=queue.Queue(maxsize=8);state={'position':0,'paused':False}
    def read_commands():
        for line in sys.stdin:
            commands.put(line.strip())
        commands.put('stop')
    threading.Thread(target=read_commands,daemon=True).start()
    def emit(event):print(json.dumps({'event':event,'pid':os.getpid(),'frequency':frequency}),flush=True)
    def tick():
        while not commands.empty():
            command=commands.get_nowait()
            if command=='stop':sink.stop();app.quit();return
            if command=='pause':sink.suspend();state['paused']=True;emit('paused')
            elif command=='resume':sink.resume();state['paused']=False;emit('resumed')
        if state['paused']:return
        for _ in range(4):
            size=min(sink.bytesFree(),len(pcm)-state['position']);size-=size%fmt.bytesPerFrame()
            if size<=0:break
            written=output.write(pcm[state['position']:state['position']+size])
            if written<=0:break
            state['position']=(state['position']+written)%len(pcm)
    timer=QTimer();timer.setInterval(10);timer.timeout.connect(tick);timer.start()
    QTimer.singleShot(25000,app.quit);emit('ready')
    result=app.exec();sink.stop();return result


def run_check(output):
    import numpy as np
    from app.audio.capture import CaptureSession
    from app.audio.diagnostics import AudioDiagnostics
    from app.audio.processing import AudioProcessor
    from app.audio.processes import ProcessSelector
    from app.audio.protocol import Kind
    if output.exists():raise FileExistsError('choose a new report path')
    workers=[];receiver=None;session_box=[];events=[];observations=[];failure=[]
    started=threading.Event();ended=threading.Event();stats=AudioDiagnostics();lock=threading.Lock()
    report={'passed':False,'source':'process_tree','real_loopback':True,'models_loaded':False,'api_requests':0}
    try:
        for frequency in (1000,440):
            process=subprocess.Popen([sys.executable,'-B','-u','-X','utf8',str(Path(__file__).resolve()),'--tone',str(frequency)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,cwd=ROOT,
                creationflags=subprocess.CREATE_NO_WINDOW)
            signals=queue.Queue(maxsize=16)
            def read_events(proc=process,q=signals):
                for line in proc.stdout:
                    try:q.put(json.loads(line))
                    except ValueError:continue
            threading.Thread(target=read_events,daemon=True).start()
            workers.append((process,signals))
        ready=[signals.get(timeout=12) for _,signals in workers]
        if not all(event['event']=='ready' for event in ready):raise RuntimeError('test players not ready')
        target=ProcessSelector().inspect(ready[0]['pid'])
        query="import json;from app.audio.processes import ProcessSelector;p,e=ProcessSelector().discover('sessions');print(json.dumps({'pids':[v.pid for v in p],'errors':e}))"
        discovered=subprocess.run([sys.executable,'-B','-c',query],cwd=ROOT,capture_output=True,timeout=10,
                                  creationflags=subprocess.CREATE_NO_WINDOW,check=True)
        mixer=json.loads(discovered.stdout)
        report['both_test_sources_discovered']=all(event['pid'] in mixer['pids'] for event in ready)
        report['discovery_errors']=mixer['errors']
        def capture():
            try:
                with CaptureSession(ROOT/'native/build/Release/elt_capture.exe',target) as session:
                    session_box.append(session);processor=AudioProcessor()
                    while True:
                        packet=session.receive()
                        if packet.kind==Kind.AUDIO:
                            for frame in processor.process(packet):
                                with lock:
                                    stats.update(frame.samples)
                                    observations.append((time.monotonic(),float(np.sqrt(np.mean(frame.samples**2)))))
                        else:
                            value=packet.json();events.append(value)
                            if value.get('state')=='started':started.set()
                            if packet.kind==Kind.ERROR:break
            except Exception as error:failure.append(str(error))
            finally:ended.set()
        receiver=threading.Thread(target=capture,daemon=True);receiver.start()
        if not started.wait(8):raise RuntimeError('native process-loopback did not start')
        time.sleep(2.5);pause_at=time.monotonic()
        workers[0][0].stdin.write(b'pause\n');workers[0][0].stdin.flush()
        assert workers[0][1].get(timeout=3)['event']=='paused'
        time.sleep(2);resume_at=time.monotonic()
        workers[0][0].stdin.write(b'resume\n');workers[0][0].stdin.flush()
        assert workers[0][1].get(timeout=3)['event']=='resumed'
        time.sleep(2.5)
        workers[0][0].stdin.write(b'stop\n');workers[0][0].stdin.flush();workers[0][0].wait(timeout=5)
        if not ended.wait(6):raise TimeoutError('capture did not end after the target exited')
        with lock:
            report.update(stats.summary());points=list(observations)
            report['isolation']=stats.isolation_status()
        report['target_exit_reported']=any('target_exited' in json.dumps(event) for event in events)
        before=[rms for timestamp,rms in points if timestamp<pause_at]
        paused=[rms for timestamp,rms in points if pause_at+.7<timestamp<resume_at-.1]
        after=[rms for timestamp,rms in points if timestamp>resume_at+.7]
        peak=max(before,default=0)
        report['pause_silent_or_no_data']=not paused or max(paused)<max(1e-5,peak*.05)
        report['resumed_nonzero']=max(after,default=0)>1e-4
        report['capture_errors']=failure
        report['helper_reaped']=bool(session_box) and session_box[0].child is None
        report['passed']=all([report['both_test_sources_discovered'],report['isolation']=='passed',
            report['pause_silent_or_no_data'],report['resumed_nonzero'],report['target_exit_reported'],report['helper_reaped'],not failure])
    except Exception as error:report['error']=str(error)
    finally:
        for process,_ in workers:
            if process.poll() is None:
                try:process.stdin.write(b'stop\n');process.stdin.flush();process.wait(timeout=3)
                except (OSError,ValueError,subprocess.TimeoutExpired):process.kill();process.wait(timeout=3)
            process.stdin.close();process.stdout.close();process.stderr.close()
        if receiver:receiver.join(timeout=6)
        if receiver and receiver.is_alive() and session_box:session_box[0].close();receiver.join(timeout=3)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0 if report['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tone',type=int,choices=(1000,440));parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.tone:return tone_worker(args.tone)
    if args.output is None:parser.error('--output is required; this check plays two short test tones')
    return run_check(args.output)


if __name__=='__main__':raise SystemExit(main())
