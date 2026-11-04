"""Render extension controls against an idle local test service; no user tabs, ASR or cloud."""
import argparse
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import httpx

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
ASSETS=ROOT/'app/web_follow/extension'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    import webview
    from app.web_follow.server import Lab,Server,options_from,READING_FIELDS
    options=options_from(dict(translate=True,narrate=True,speech_engine='qwen',tts_model='1.7B',tts_voice='lecture_male',language='en'))
    result={};errors=[];lab=Lab();temp=tempfile.TemporaryDirectory(dir=args.output)
    service=Server(lab,preferences_path=Path(temp.name)/'settings.json',desktop_options=options)
    service_thread=threading.Thread(target=service.serve_forever,daemon=True);service_thread.start()
    client=httpx.Client(base_url=service.origin,trust_env=False,timeout=5)
    extension='a'*32;headers={'Origin':'chrome-extension://'+extension,'X-ELT-Extension-Id':extension,'X-ELT-Lab-Token':service.token}
    paired=client.post('/bridge/pair',headers=headers,json={});paired.raise_for_status()
    client.headers.update({'Origin':headers['Origin'],'X-ELT-Extension-Id':extension,'X-ELT-Bridge-Token':paired.json()['token']})
    runtime='''window.chrome={runtime:{sendMessage:async m=>{
      if(m.kind==='ELT_STATUS')return fetch('/preview/status').then(r=>r.json());
      if(m.kind==='ELT_GET_READING')return fetch('/preview/settings').then(r=>r.json());
      if(m.kind==='ELT_SET_PLAYBACK')return fetch('/preview/playback',{method:'POST',body:JSON.stringify(m.options)}).then(r=>r.json());
      return {error:'这是独立控件测试，不会启动课程。'};
    }},tabs:{query:async()=>[{id:1}]}};'''
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*a,**kw):super().__init__(*a,directory=str(ASSETS),**kw)
        def log_message(self,*a):pass
        def raw(self,data,mime):
            self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_GET(self):
            if self.path=='/preview-runtime.js':self.raw(runtime.encode(),'text/javascript');return
            if self.path in ('/preview/status','/preview/settings'):
                route='/bridge/status' if self.path.endswith('status') else '/bridge/settings'
                self.raw(client.get(route).content,'application/json');return
            if self.path=='/popup.html':
                html=(ASSETS/'popup.html').read_text(encoding='utf-8').replace('<script src="popup.js">','<script src="/preview-runtime.js"></script><script src="popup.js">')
                self.raw(html.encode(),'text/html; charset=utf-8');return
            super().do_GET()
        def do_POST(self):
            length=int(self.headers.get('Content-Length','0'))
            if self.path!='/preview/playback' or not 0<length<4096:self.send_error(400);return
            response=client.post('/bridge/playback',json={'options':json.loads(self.rfile.read(length))})
            self.raw(response.content,'application/json')
    http=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    url=f'http://127.0.0.1:{http.server_port}/popup.html'
    window=webview.create_window('ELT · 网页扩展界面测试',url,width=460,height=650)
    def ui(fn):
        from System import Action
        done=threading.Event()
        def apply():
            try:fn()
            except BaseException as error:errors.append(type(error).__name__+': '+str(error))
            finally:done.set()
        window.native.BeginInvoke(Action(apply));assert done.wait(10),'UI callback timed out'
        assert not errors,errors
    def wait_js(code):
        deadline=time.monotonic()+15
        while not window.evaluate_js(code):
            if time.monotonic()>deadline:raise AssertionError('popup did not finish loading or applying settings')
            time.sleep(.1)
    def run():
        stream=None
        try:
            wait_js("!document.getElementById('reading').disabled")
            window.evaluate_js('''for(const [id,value] of [['speed','1.2'],['volume','65'],['source','35']]){
              const control=document.getElementById(id);control.value=value;control.dispatchEvent(new Event('change'));}''')
            wait_js("document.getElementById('message').textContent.startsWith('已保存')")
            deadline=time.monotonic()+10
            while lab.options.get('source_percent')!=35 or lab.options.get('volume')!=65:
                if time.monotonic()>deadline:raise AssertionError('popup settings were not applied to real local service')
                time.sleep(.1)
            assert lab.options['base_speed']==1.2 and lab.process is None
            result['real_http_changes']={key:lab.options[key] for key in ('volume','base_speed','source_percent')}
            window.evaluate_js("document.getElementById('captionWidth').value=65;document.getElementById('captionWidth').dispatchEvent(new Event('change'))")
            wait_js("document.getElementById('message').textContent.includes('已保存')")
            deadline=time.monotonic()+5
            while lab.options.get('caption_width')!=65:
                if time.monotonic()>deadline:raise AssertionError('caption size did not reach real settings API')
                time.sleep(.05)
            result['real_caption_width']=lab.options['caption_width']
            result['asr_started']=lab.process is not None
            window.evaluate_js('''for(const [id,value] of [['speed','1.00'],['volume','80'],['source','20']]){
              const control=document.getElementById(id);control.value=value;control.dispatchEvent(new Event('change'));}''')
            deadline=time.monotonic()+10
            while lab.options.get('source_percent')!=20 or lab.options.get('volume')!=80:
                if time.monotonic()>deadline:raise AssertionError('popup defaults were not restored through its controls')
                time.sleep(.1)
            bounds=window.evaluate_js('''(()=>{const b=document.body.getBoundingClientRect();return {width:b.width,height:b.height,ratio:devicePixelRatio};})()''')
            from System.Drawing import Size
            ui(lambda:setattr(window.native,'ClientSize',Size(round(bounds['width']*bounds['ratio']),round(bounds['height']*bounds['ratio']))))
            time.sleep(.2)
            result['layout']=window.evaluate_js('''(()=>{const b=document.body.getBoundingClientRect();return {width:b.width,height:b.height,
              scrollWidth:document.documentElement.scrollWidth,viewport:innerWidth,ready:!document.getElementById('reading').disabled};})()''')
            assert result['layout']['scrollWidth']<=result['layout']['viewport']
            from System.IO import FileStream,FileMode
            from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
            stream=FileStream(str((args.output/'popup.png').resolve()),FileMode.Create);capture=[]
            ui(lambda:capture.append(window.native.webview.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,stream)))
            task=capture[0];deadline=time.monotonic()+10
            while not task.IsCompleted:
                if time.monotonic()>deadline:raise TimeoutError('preview capture timed out')
                time.sleep(.05)
            task.GetAwaiter().GetResult();stream.Close();stream=None
            result['preview_captured']=True
        except BaseException as error:
            import traceback
            print(traceback.format_exc(),flush=True)
            errors.append(type(error).__name__+': '+str(error));result['errors']=errors
        finally:
            if stream:stream.Close()
            (args.output/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            window.destroy()
    try:webview.start(run,gui='edgechromium',private_mode=True,storage_path=str(Path(temp.name)/'browser'))
    finally:
        http.shutdown();http.server_close();thread.join(2);client.close()
        service.shutdown();service.server_close();lab.close();service_thread.join(2);temp.cleanup()
    print(json.dumps(result,ensure_ascii=False));return 1 if errors else 0


if __name__=='__main__':raise SystemExit(main())
