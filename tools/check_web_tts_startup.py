"""Real continuous-clock Qwen startup check; fixed test text, no ASR or cloud API."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time
from types import SimpleNamespace
import wave

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model-size',choices=['0.6B','1.7B'],default='1.7B')
    p.add_argument('--voice',default='lecture_male');p.add_argument('--play',action='store_true');args=p.parse_args()
    import psutil
    from app.web_follow.tts import SpeechQueue,settings
    from app.web_follow.timeline import Cue
    args.output.parent.mkdir(parents=True,exist_ok=True)
    directory=args.output.parent/'generated-test-speech';directory.mkdir(exist_ok=True)
    started=time.monotonic();clock=SimpleNamespace(value=0.);events=[];pids=set();ready=None
    report={'model_size':args.model_size,'voice':args.voice,'device':'cuda',
            'method':'Continuously advancing 1x test clock while the first cue expires; fixed Chinese test text only',
            'cloud_requests':0,'test_audio_saved':True,'attempts':[]};stream=None;failure=None
    def receive(kind,**value):
        events.append((time.monotonic(),kind,value))
        if kind=='tts_status' and value.get('pid'):pids.add(value['pid'])
    try:
        stream=SpeechQueue(settings(dict(speech_engine='qwen',tts_model=args.model_size,tts_voice=args.voice)),
            directory,SimpleNamespace(value=1),receive,clock)
        stream.offer(1,Cue('expired-at-startup',0,.05,'test fixture',translation='启动期间会过期的测试句。'))
        deadline=started+240;cursor=0;pending=None;attempt=0;done=None
        while time.monotonic()<deadline:
            now=time.monotonic();clock.value=now-started
            fresh=events[cursor:];cursor=len(events)
            for stamp,kind,value in fresh:
                if kind=='tts_status' and value.get('status')=='ready' and ready is None:
                    ready=stamp;report['model_ready_seconds']=round(stamp-started,3)
                if kind=='tts_status' and value.get('disabled'):raise RuntimeError('local TTS disabled after repeated failures')
                if kind=='speech_cue' and value['cue'].get('speech'):
                    if value['cue']['id']=='expired-at-startup':raise AssertionError('expired startup speech was published')
                    cue=value['cue'];done=cue
                    report['attempts'][-1]['preparation_seconds']=round(stamp-pending,3)
                    break
                if kind=='tts_status' and value.get('status')=='skipped':
                    if pending is not None:report['attempts'][-1]['expired']=True
                    pending=None
            if done:break
            if ready is not None and pending is None and attempt<3:
                attempt+=1;pending=now
                identity=f'current-{attempt}';report['attempts'].append({'id':identity,'expired':False})
                stream.offer(1,Cue(identity,clock.value+3,clock.value+18,'test fixture',
                    translation='现在开始中文朗读。字幕和声音会跟随课程视频。'))
            time.sleep(.05)
        if not done:raise TimeoutError('no current speech produced before test deadline')
        source=directory/done['speech'];sample=args.output.parent/'chinese-reading-test.wav';shutil.copyfile(source,sample)
        import numpy as np
        with wave.open(str(sample),'rb') as audio:
            pcm=np.frombuffer(audio.readframes(audio.getnframes()),dtype='<i2').astype(np.float32)/32768
            report.update(audio_seconds=audio.getnframes()/audio.getframerate(),sample_rate=audio.getframerate(),
                          rms=float(np.sqrt(np.mean(pcm*pcm))),sample_file=sample.name)
        assert report['rms']>1e-5 and report['audio_seconds']>0
        report['model_load_count']=len(pids);assert len(pids)==1,'model unexpectedly reloaded'
        report['first_expired_cue_not_published']=not any(k=='speech_cue' and v['cue'].get('speech') and
            v['cue']['id']=='expired-at-startup' for _,k,v in events)
        report['ready_device']=stream.state.get('device')
        if args.play:
            import winsound
            winsound.PlaySound(str(sample.resolve()),winsound.SND_FILENAME);report['test_audio_playback_completed']=True
    except BaseException as error:
        failure=error;report['error']=type(error).__name__+': '+str(error)
    finally:
        if stream:stream.close()
        report['tts_processes_reaped']=all(not psutil.pid_exists(pid) for pid in pids)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return 1 if failure else 0


if __name__=='__main__':raise SystemExit(main())
