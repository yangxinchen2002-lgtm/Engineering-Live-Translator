"""Real per-process attenuation/restoration, owner-death recovery and ASR speech checks.

Only dedicated test VLC processes are modified. No cloud API or user media.
"""
import sys
sys.coinit_flags=0
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import re
import subprocess
import time
import wave
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.audio.processes import ProcessInfo,ProcessSelector
from app.audio.source_volume import CoreAudioBackend,SourceAttenuator
from live_checks import Player


def wait_for(app,predicate,seconds=12):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        app.processEvents()
        if predicate():return
        time.sleep(.025)
    raise TimeoutError('source volume did not reach the expected state')


def sessions_for(backend,pid):return [s for s in backend.sessions() if s.pid==pid]


def volume(backend,pid):
    sessions=sessions_for(backend,pid)
    if not sessions:raise RuntimeError('test audio session missing')
    return sessions[0].get_volume()


def masters(backend):
    import comtypes
    from pycaw.api.endpointvolume import IAudioEndpointVolume
    collection=backend.enumerator.EnumAudioEndpoints(0,1);result={}
    for index in range(collection.GetCount()):
        device=collection.Item(index)
        endpoint=device.Activate(IAudioEndpointVolume._iid_,comtypes.CLSCTX_ALL,None).QueryInterface(IAudioEndpointVolume)
        result[device.GetId()]=float(endpoint.GetMasterVolumeLevelScalar())
    return result


def owner_mode(target):
    from PySide6.QtCore import QCoreApplication
    from app.ui.source_volume import SourceVolumeController
    app=QCoreApplication([]);controller=SourceVolumeController();controller.set_target(ProcessInfo(**json.loads(target)),20)
    return app.exec()


def capture_speech(media,percent,directory,worker,identity):
    from app.audio.capture import CaptureSession
    from app.audio.processing import AudioProcessor
    from app.audio.protocol import Kind
    from app.asr.types import ASRJob
    player=Player(ROOT/'tools/vlc-3.0.24/vlc.exe',media,directory/f'vlc-speech-{percent}.txt',ready_timeout=60)
    player.command('pause');target=ProcessSelector().inspect(player.child.pid)
    backend=CoreAudioBackend();attenuator=SourceAttenuator(target,backend);session=None;samples=[];processor=AudioProcessor();resumed=False
    try:
        attenuator.update(percent);session=CaptureSession(ROOT/'native/build/Release/elt_capture.exe',target)
        applied=False
        while True:
            packet=session.receive()
            if packet.kind==Kind.ERROR:raise RuntimeError(packet.json())
            if packet.kind!=Kind.AUDIO:continue
            if not resumed:player.command('seek 0');player.command('pause');resumed=True
            if not applied and attenuator.update(percent):applied=True
            for frame in processor.process(packet):samples.append(frame.samples)
            if processor.output_samples>=12*16000:break
        audio=np.concatenate(samples)
        submitted=time.perf_counter_ns();worker.submit(ASRJob(identity,1,0,len(audio),audio,True,True,submitted,submitted,language='en'))
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            message=worker.poll()
            if message and message['type']=='result':
                result=message['result'];worker.busy=None
                return {'percent':percent,'text':result.text,'captured_seconds':len(audio)/16000,
                        'rms':float(np.sqrt(np.mean(audio.astype('float64')**2))),'volume_applied':applied}
            time.sleep(.005)
        raise TimeoutError('ASR test timed out')
    finally:
        attenuator.restore()
        if session:session.close()
        player.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);parser.add_argument('--owner-target')
    args=parser.parse_args()
    if args.owner_target:return owner_mode(args.owner_target)
    if args.output is None:parser.error('--output is required')
    directory=args.output.resolve();directory.mkdir(parents=True,exist_ok=False)
    from PySide6.QtCore import QCoreApplication
    from app.ui.source_volume import SourceVolumeController
    app=QCoreApplication([]);backend=CoreAudioBackend();players=[];controller=SourceVolumeController();owner=None;worker=None;result={}
    tone=directory/'quiet-tone.wav';rate=48000
    with wave.open(str(tone),'wb') as output:
        output.setparams((1,2,rate,0,'NONE','not compressed'))
        output.writeframes((np.sin(np.arange(rate*16)*2*np.pi*440/rate)*700).astype('<i2').tobytes())
    try:
        for index in range(2):
            print('Starting dedicated test VLC',index,flush=True)
            players.append(Player(ROOT/'tools/vlc-3.0.24/vlc.exe',tone,directory/f'vlc-{index}.txt',ready_timeout=120))
        target=ProcessSelector().inspect(players[0].child.pid);other=players[1].child.pid
        original=volume(backend,target.pid);unrelated=volume(backend,other);device_before=masters(backend)
        controller.set_target(target,20);wait_for(app,lambda:abs(volume(backend,target.pid)-original*.2)<1e-4)
        result['attenuated']=volume(backend,target.pid);result['original']=original
        result['other_application_unchanged']=abs(volume(backend,other)-unrelated)<1e-4
        result['master_volume_unchanged']=masters(backend)==device_before
        controller.set_target(target,40);wait_for(app,lambda:abs(volume(backend,target.pid)-original*.4)<1e-4)
        result['changed_ratio']=volume(backend,target.pid)
        controller.set_target(None);wait_for(app,lambda:abs(volume(backend,target.pid)-original)<1e-4)
        result['normal_restore']=volume(backend,target.pid)
        owner=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--owner-target',json.dumps(asdict(target))],
                               cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        wait_for(app,lambda:abs(volume(backend,target.pid)-original*.2)<1e-4)
        owner.terminate();owner.wait(5);wait_for(app,lambda:abs(volume(backend,target.pid)-original)<1e-4)
        result['owner_death_restore']=volume(backend,target.pid)
        for player in players:player.close()
        players.clear()
        from qwen_tts_lab import load_asr
        from measure_local_translation import audio_excerpt
        source=audio_excerpt(ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4',28)[20*16000:28*16000]
        padded=np.concatenate((np.zeros(2*16000,np.float32),source,np.zeros(4*16000,np.float32)))
        media=directory/'public-speech.wav'
        with wave.open(str(media),'wb') as output:
            output.setparams((1,2,16000,0,'NONE','not compressed'));output.writeframes((np.clip(padded,-1,1)*32767).astype('<i2').tobytes())
        worker,ready=load_asr();result['asr_ready']=ready
        result['speech']=[capture_speech(media,percent,directory,worker,index) for index,percent in enumerate((100,20,10))]
        normal=lambda value:re.sub(r'[^a-z0-9]','',value.lower())
        expected=normal(result['speech'][0]['text'])
        result['asr_same_words']=bool(expected) and all(normal(row['text'])==expected for row in result['speech'])
        result['passed']=bool(result['other_application_unchanged'] and result['master_volume_unchanged'] and result['asr_same_words']
                              and all(row['volume_applied'] for row in result['speech']))
    except Exception as error:result.update(passed=False,error=type(error).__name__+': '+str(error))
    finally:
        controller.close()
        if owner and owner.poll() is None:owner.terminate();owner.wait(5)
        if worker:worker.close()
        for player in players:player.close()
        (directory/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    return 0 if result['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
