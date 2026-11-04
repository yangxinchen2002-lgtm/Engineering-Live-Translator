"""Real WebView2/MP4/iframe smoke using only an existing public local fixture."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--hold-seconds',type=int,default=0,choices=range(61))
    p.add_argument('--toolbar-preview',type=Path,help='render actual native controls with a local idle service; no ASR or cloud')
    args=p.parse_args()
    import webview
    from app.web_follow.player import Player,WELCOME,configure_audio_playback
    configure_audio_playback()
    result={};errors=[];args.output.parent.mkdir(parents=True,exist_ok=True)
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self,*a):pass
        def copyfile(self,*a):
            try:super().copyfile(*a)
            except (ConnectionAbortedError,ConnectionResetError,BrokenPipeError):pass
    http=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(ROOT/'tests/fixtures/public-m1')))
    threading.Thread(target=http.serve_forever,daemon=True).start()
    w=webview.create_window('ELT · 课程窗口测试',html=WELCOME,width=1100,height=800)
    player=Player(w)
    preview_lab=preview_server=preview_thread=None
    if args.toolbar_preview:
        import httpx
        from app.web_follow.server import Lab,Server,options_from
        options=options_from(dict(translate=True,narrate=True,speech_engine='qwen',tts_model='1.7B',tts_voice='lecture_male'))
        preview_lab=Lab();preview_server=Server(preview_lab,desktop_options=options)
        preview_thread=threading.Thread(target=preview_server.serve_forever,daemon=True);preview_thread.start()
        player.client=httpx.Client(base_url=preview_server.origin,headers={'X-ELT-Lab-Token':preview_server.token},trust_env=False,timeout=5)
        player._request('/api/state');player.options=options
    def install_checked():
        try:player.install()
        except BaseException as error:
            import traceback
            errors.append(type(error).__name__+': '+str(error));print(traceback.format_exc(),flush=True)
    w.events.loaded+=lambda:player.ui(install_checked)
    def run():
        try:
            limit=time.monotonic()+30
            while player.status is None and not errors and time.monotonic()<limit:time.sleep(.1)
            assert not errors,errors
            assert player.status is not None,'formal player toolbar did not initialize'
            result['formal_toolbar_installed']=True
            assert len(player.reading_controls)==8,'source-volume toolbar controls missing'
            controls_ready=threading.Event()
            def inspect_controls():
                check,speed,volume,amount,model,voice,duck,percent=player.reading_controls
                result['source_volume_controls']={'checked':bool(duck.Checked),'percent':int(str(percent.Value)),
                                                   'model_selected':int(model.SelectedIndex),'voice_selected':int(voice.SelectedIndex)}
                controls_ready.set()
            player.ui(inspect_controls);assert controls_ready.wait(5),'toolbar values not available'
            assert result['source_volume_controls']['percent']==20
            assert result['source_volume_controls']['model_selected']>=0
            assert result['source_volume_controls']['voice_selected']>=0
            events_ready=threading.Event()
            def check_control_events():
                from System import Decimal
                *_,duck,percent=player.reading_controls
                duck.Checked=False;percent.Value=Decimal(35)
                result['source_volume_control_events']=dict(player.pending_playback)
                player.update_reading_controls();events_ready.set()
            player.ui(check_control_events);assert events_ready.wait(5),'toolbar events not available'
            assert result['source_volume_control_events']=={'duck_source':False,'source_percent':35}
            events_ready.clear()
            def check_caption_controls():
                from System import Decimal
                player.pending_playback.clear()
                for key,value in (('caption_width',65),('caption_height',96),('caption_font_size',14)):
                    player.caption_controls[key].Value=Decimal(value)
                result['caption_control_events']=dict(player.pending_playback)
                player.pending_playback.clear();player.update_reading_controls();events_ready.set()
            player.ui(check_caption_controls);assert events_ready.wait(5)
            assert result['caption_control_events']=={'caption_width':65,'caption_height':96,'caption_font_size':14}
            result['source_volume_toolbar_installed']=True
            result['h264']=w.evaluate_js("document.createElement('video').canPlayType('video/mp4; codecs=\"avc1.42E01E, mp4a.40.2\"')")
            assert result['h264'],'H264 codec missing'
            src=f'http://127.0.0.1:{http.server_port}/en-linear-algebra.mp4'
            fixture=f'<h2>ELT 内置课程窗口 · 公开样本播放测试</h2><p>真实本地 MP4，非课程网站登录验收。</p><video autoplay muted controls width="900" src="{src}"></video><iframe srcdoc="<p>Frame check</p>"></iframe>'
            w.evaluate_js('document.body.innerHTML='+json.dumps(fixture))
            limit=time.monotonic()+20;state={}
            while time.monotonic()<limit:
                state=w.evaluate_js("(()=>{const v=document.querySelector('video');return v?{time:v.currentTime,ready:v.readyState,error:v.error?.code||0}:{};})()")
                if state.get('time',0)>.5:break
                time.sleep(.2)
            result['mp4_playback']=state
            if not state:result['fixture_dom']=w.evaluate_js('document.body.innerHTML.slice(0,700)')
            assert state.get('time',0)>.5 and state.get('error')==0
            result['iframe_created']=bool(player.handles);assert result['iframe_created']
            # Real HTMLMediaElement and production volume guard; this public
            # muted fixture is independent of the user's active course window.
            volume_code='\n'.join((ROOT/'app/web_follow'/name).read_text(encoding='utf-8')
                                  for name in ('extension/core.js','extension/source-volume.js'))
            w.evaluate_js(volume_code+'''
                window.duckCheckNow=0;
                window.duckCheck=new ELTFollow.SourceVolume(()=>window.duckCheckNow);
                var v=document.querySelector('video');v.volume=.65;
                window.duckCheck.command({active:true,percent:20});window.duckCheck.tick(v);
            ''')
            levels={}
            levels['ducked']=w.evaluate_js("document.querySelector('video').volume")
            assert abs(levels['ducked']-.13)<.00001
            w.evaluate_js("for(var i=0;i<20;i++)window.duckCheck.tick(document.querySelector('video'))")
            assert abs(w.evaluate_js("document.querySelector('video').volume")-.13)<.00001
            w.evaluate_js("window.duckCheck.command({active:true,percent:50});window.duckCheck.tick(document.querySelector('video'))")
            levels['adjusted']=w.evaluate_js("document.querySelector('video').volume")
            assert abs(levels['adjusted']-.325)<.00001
            w.evaluate_js("window.duckCheck.command({active:false})")
            levels['restored']=w.evaluate_js("document.querySelector('video').volume")
            assert abs(levels['restored']-.65)<.00001
            w.evaluate_js("window.duckCheck.command({active:true,percent:20});window.duckCheck.tick(document.querySelector('video'));window.duckCheckNow=1501;window.duckCheck.tick(document.querySelector('video'))")
            levels['after_lost_heartbeat']=w.evaluate_js("document.querySelector('video').volume")
            assert abs(levels['after_lost_heartbeat']-.65)<.00001
            assert not w.evaluate_js("document.querySelector('video').paused")
            result['source_volume_real_media']=levels
            # Production shared caption DOM, on this independent public fixture.
            layout=(ROOT/'app/web_follow/extension/layout.js').read_text(encoding='utf-8')
            w.evaluate_js(layout+'''window.captionTest=document.createElement('div');document.body.append(captionTest);
                window.captionRoot=captionTest.attachShadow({mode:'open'});
                captionRoot.innerHTML='<style>'+ELTFollow.captionCSS+'</style>'+ELTFollow.captionMarkup;
                window.paintTest=(text,options)=>{
                  ELTFollow.placeCaption(captionTest,document.querySelector('video').getBoundingClientRect(),options,{width:innerWidth,height:innerHeight});
                  ELTFollow.renderCaption(captionTest,captionRoot.querySelector('#o'),captionRoot.querySelector('#t'),captionRoot.querySelector('#elt-unlock'),text,options);
                };paintTest({source:'A complete engineering sentence.',translation:'这是一句完整的工科译文。'},{});''')
            result['compact_short_caption']=w.evaluate_js("({height:captionRoot.querySelector('section').getBoundingClientRect().height,closeWidth:captionRoot.querySelector('#elt-close').getBoundingClientRect().width,statusRows:captionRoot.querySelectorAll('small').length})")
            assert result['compact_short_caption']['height']<90 and result['compact_short_caption']['closeWidth']<=24
            assert result['compact_short_caption']['statusRows']==0
            w.evaluate_js("paintTest({source:'Long sentence. '.repeat(100),translation:'长句测试，'.repeat(120)},{caption_width:55,caption_height:96,caption_font_size:14})")
            result['long_caption']=w.evaluate_js("({width:captionTest.getBoundingClientRect().width,height:captionRoot.querySelector('section').getBoundingClientRect().height,textLength:captionRoot.querySelector('#t').textContent.length,scrollHeight:captionRoot.querySelector('section').scrollHeight})")
            assert abs(result['long_caption']['width']-495)<2 and result['long_caption']['height']<=97
            assert result['long_caption']['textLength']==600 and result['long_caption']['scrollHeight']>96
            close_top=w.evaluate_js("captionRoot.querySelector('#elt-close').getBoundingClientRect().top")
            w.evaluate_js("captionRoot.querySelector('section').scrollTop=180")
            assert abs(w.evaluate_js("captionRoot.querySelector('#elt-close').getBoundingClientRect().top")-close_top)<1
            result['close_remains_visible_while_scrolling']=True
            w.evaluate_js("paintTest(null,{});")
            assert w.evaluate_js("captionTest.hidden") is True
            w.evaluate_js("captionTest.remove()")
            before=w.evaluate_js("document.querySelector('video').currentTime")
            player.stop_render();time.sleep(.25)
            assert w.evaluate_js("document.querySelector('video').currentTime")>before
            assert not w.evaluate_js("document.querySelector('video').paused")
            result['stop_did_not_pause_test_video']=True
            w.evaluate_js("document.querySelector('video').pause()")  # Test fixture only.
            before=w.evaluate_js("document.querySelector('video').currentTime")
            player.stop_render()
            assert w.evaluate_js("document.querySelector('video').paused") is True
            result['stop_did_not_change_test_player_state']=True
            if args.toolbar_preview:
                rendered=threading.Event()
                def render_toolbar():
                    from System.Drawing import Bitmap,Rectangle,Size
                    from System.Drawing.Imaging import ImageFormat
                    from System.Windows.Forms import Label,Button,TextBox,TextRenderer
                    try:
                        form=w.native;factor=float(form.DeviceDpi)/96
                        result['toolbar_dpi']=int(form.DeviceDpi);result['toolbar_layouts']=[]
                        def all_controls(parent):
                            for child in parent.Controls:
                                yield child
                                yield from all_controls(child)
                        for width in (800,1240,1600):
                            form.ClientSize=Size(round(width*factor),round(740*factor));form.PerformLayout();player.toolbar.PerformLayout()
                            clipped=[]
                            for child in all_controls(player.toolbar):
                                if isinstance(child,(Label,Button)) and child.Text:
                                    required=TextRenderer.MeasureText(child.Text,child.Font).Width
                                    if required>child.ClientSize.Width+2:clipped.append({'text':child.Text,'width':child.Width,'required':required})
                            groups=[dict(x=c.Left,y=c.Top,width=c.Width,height=c.Height) for c in player.toolbar_groups]
                            address=next(c for c in all_controls(player.toolbar) if isinstance(c,TextBox) and c.AccessibleName=='课程网址')
                            assert address.Width>=180,'course address field became too narrow'
                            result['toolbar_layouts'].append(dict(width=width,height=player.toolbar.Height,address_width=address.Width,groups=groups,clipped_labels=clipped))
                            args.toolbar_preview.parent.mkdir(parents=True,exist_ok=True)
                            path=args.toolbar_preview.with_name(args.toolbar_preview.stem+f'-{width}.png')
                            bitmap=Bitmap(player.toolbar.Width,player.toolbar.Height)
                            try:
                                player.toolbar.DrawToBitmap(bitmap,Rectangle(0,0,bitmap.Width,bitmap.Height));bitmap.Save(str(path.resolve()),ImageFormat.Png)
                                if width==1240:bitmap.Save(str(args.toolbar_preview.resolve()),ImageFormat.Png)
                            finally:bitmap.Dispose()
                        form.ClientSize=Size(round(1240*factor),round(740*factor))
                    except BaseException as error:errors.append(type(error).__name__+': '+str(error))
                    finally:rendered.set()
                player.ui(render_toolbar);assert rendered.wait(10),'toolbar preview timed out'
                assert not errors,errors
                assert not any(row['clipped_labels'] for row in result['toolbar_layouts']),result['toolbar_layouts']
        except BaseException as e:errors.append(type(e).__name__+': '+str(e));result['errors']=errors
        finally:
            args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            if args.hold_seconds:time.sleep(args.hold_seconds)
            w.destroy()
    try:
        with tempfile.TemporaryDirectory(prefix='ELT-Player-Check-') as profile:
            webview.start(run,gui='edgechromium',private_mode=True,storage_path=profile)
    finally:
        player.close_local()
        http.shutdown();http.server_close()
        if player.client:player.client.close();player.client=None
        if preview_server:preview_server.shutdown();preview_server.server_close();preview_lab.close();preview_thread.join(2)
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 1 if errors else 0


if __name__=='__main__':raise SystemExit(main())
