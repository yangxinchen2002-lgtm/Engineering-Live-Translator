"""Real local-file player/clock check; optional real GPU/text translation/local TTS."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
import httpx

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path,default=ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4')
    p.add_argument('--gpu',action='store_true');p.add_argument('--translate',action='store_true');p.add_argument('--narrate',action='store_true')
    p.add_argument('--hold-seconds',type=int,default=0,choices=range(46));args=p.parse_args()
    if (args.translate or args.narrate) and not args.gpu:p.error('translation/narration requires --gpu')
    if args.narrate and not args.translate:p.error('narration requires --translate')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    import webview
    from app.web_follow.player import Player,WELCOME,configure_audio_playback
    from app.web_follow.server import Lab,Server,options_from
    configure_audio_playback();result={};errors=[];lab=service=service_thread=None
    w=webview.create_window('ELT · 本地视频预读测试',html=WELCOME,width=1240,height=860)
    player=Player(w)
    def install():
        try:player.install()
        except BaseException as error:errors.append(type(error).__name__+': '+str(error))
    w.events.loaded+=lambda:player.ui(install)
    w.events.closed+=lambda:player.exit.set()
    def wait(predicate,label,seconds=20):
        deadline=time.monotonic()+seconds
        while not predicate():
            if errors:raise AssertionError(errors)
            if time.monotonic()>deadline:raise TimeoutError(label)
            time.sleep(.1)
    def js(code):return w.evaluate_js(code)
    def run():
        nonlocal lab,service,service_thread
        started=time.monotonic()
        try:
            wait(lambda:player.status is not None,'native toolbar')
            player.thread=threading.Thread(target=player.loop,daemon=True);player.thread.start()
            if args.gpu:
                lab=Lab();options=options_from(dict(language='en',translate=args.translate,narrate=args.narrate,
                    speech_engine='qwen',tts_model='1.7B',tts_voice='lecture_male',volume=35,base_speed=1))
                service=Server(lab,desktop_options=options);service_thread=threading.Thread(target=service.serve_forever,daemon=True);service_thread.start()
                player.enqueue('CONNECT',url=service.origin+'/#'+service.token)
                wait(lambda:player.client is not None,'caption service')
            player.enqueue('LOCAL_FILE',path=str(args.source.resolve()))
            wait(lambda:bool(js("document.querySelector('video')?.readyState>=2")),'actual local video metadata')
            js("document.querySelector('video').muted=true;document.querySelector('video').currentTime=20")
            wait(lambda:bool(player.frames),'local observer clock')
            result['real_file_playable']=True;result['local_clock_received']=True
            wait(lambda:abs(js("document.querySelector('video').currentTime")-20)<.2,'initial seek')
            if lab:
                wait(lambda:lab.source is not None and not lab.source.remote,'local ASR source')
                def prepared():
                    state=lab.state()
                    if state['error']:raise AssertionError('real pipeline failed: '+state['error'])
                    cues=[c for c in state['cues'] if c.get('asr_confirmed') and c['end']>20]
                    if args.narrate:return any(c.get('speech') for c in cues)
                    if args.translate:return any(c.get('translation') for c in cues)
                    return bool(cues)
                wait(prepared,'real source/translation/speech preparation',180)
                snapshot=lab.state();result['prepared_seconds']=round(time.monotonic()-started,3)
                result['pipeline']={'source_kind':snapshot['source_kind'],'device':snapshot['metrics'].get('device'),
                    'source_cues':sum(bool(c.get('asr_confirmed')) for c in snapshot['cues']),
                    'translated_cues':sum(bool(c.get('translation')) for c in snapshot['cues']),
                    'speech_cues':sum(bool(c.get('speech')) for c in snapshot['cues']),
                    'prepared_until':snapshot['prepared_until'],'tts':snapshot['metrics'].get('tts',{}),
                    'usage':snapshot['metrics'].get('usage',{})}
            js("document.querySelector('video').play()")
            wait(lambda:js("document.querySelector('video').currentTime")>20.4,'local playback advance')
            if args.narrate:wait(lambda:player.playback_counts['playing']>0,'actual Chinese Audio playing event',50)
            result['playback_counts']=dict(player.playback_counts)
            # These mutations operate only on this tool's public test video.
            js("document.querySelector('video').pause()")
            at=js("document.querySelector('video').currentTime");time.sleep(.3)
            assert abs(js("document.querySelector('video').currentTime")-at)<.03
            result['manual_pause']=True
            js("document.querySelector('video').playbackRate=1.25;document.querySelector('video').play()")
            wait(lambda:js("document.querySelector('video').currentTime")>at+.3,'manual resume')
            result['manual_resume_and_rate']=js("document.querySelector('video').playbackRate")==1.25
            generation=lab.timeline.generation if lab else None
            js("document.querySelector('video').currentTime=100")
            wait(lambda:js("document.querySelector('video').currentTime")>=100,'manual seek')
            if lab:wait(lambda:lab.timeline.generation>generation,'seek invalidation')
            result['manual_seek']=True
            before=js("document.querySelector('video').currentTime")
            player.enqueue('STOP');wait(lambda:not player.following and (lab is None or lab.source is None),'caption stop',20)
            time.sleep(.3)
            result['stop_did_not_pause_video']=js("!document.querySelector('video').paused&&document.querySelector('video').currentTime")>before
            assert result['stop_did_not_pause_video']
            with httpx.Client(trust_env=False) as client:
                response=client.get(player.local_host.origin+'/m/'+player.local_host.selection.token,headers={'Range':'bytes=0-31'})
                assert response.status_code==206;result['media_still_readable_after_caption_stop']=True
            if lab:result['asr_released']=lab.process is None
            if lab:result['final_usage']=lab.metrics.get('usage',{})
        except BaseException as error:
            import traceback
            print(traceback.format_exc(),flush=True);errors.append(type(error).__name__+': '+str(error));result['errors']=errors
        finally:
            args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            if args.hold_seconds:time.sleep(args.hold_seconds)
            w.destroy()
    try:webview.start(run,gui='edgechromium',private_mode=True)
    finally:
        player.exit.set()
        if player.thread:player.thread.join(10)
        player.close_local()
        if service:service.shutdown();service.server_close();lab.close();service_thread.join(2)
    print(json.dumps(result,ensure_ascii=False));return 1 if errors else 0


if __name__=='__main__':raise SystemExit(main())
