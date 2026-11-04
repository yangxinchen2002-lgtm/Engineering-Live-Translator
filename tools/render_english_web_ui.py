"""Render owned UI fixtures in the installed WebView2; never attaches to a course."""
import argparse
import json
from pathlib import Path
import re
import sys
import threading

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    from app.i18n import set_language
    set_language('en')
    import webview
    assets=ROOT/'app/web_follow';locale=(assets/'web/ui-locale.js').read_text('utf-8')
    html=(assets/'extension/popup.html').read_text('utf-8')
    html=re.sub(r'<script\b[^>]*>.*?</script>','',html,flags=re.S)
    html=re.sub(r'<link[^>]+>','<style>'+(assets/'extension/popup.css').read_text('utf-8')+'</style>',html)
    import base64
    html=html.replace('src="icon48.png"','src="data:image/png;base64,'+base64.b64encode((assets/'extension/icon48.png').read_bytes()).decode()+'"')
    fixture='''
    chrome.runtime={sendMessage:async message=>message.kind==='ELT_STATUS'?{paired:true,ui_language:'en'}:
      {translate:true,language:'de',ui_language:'en',target_language:'en',
       playback:{ui_language:'en',target_language:'en',speech_engine:'qwen',tts_model:'1.7B',tts_voice:'aiden',
        narrate:true,volume:80,base_speed:1,duck_source:true,source_percent:20},
       tts_voices:[{id:'aiden',label:'Aiden · English male'}],voices:[{id:1,label:'Microsoft David Desktop - English'}]}};
    chrome.tabs={query:async()=>[{id:1}]};
    '''
    html=html.replace('</body>','<script>'+locale+fixture+(assets/'extension/popup.js').read_text('utf-8')+'</script></body>')
    window=webview.create_window('ELT English UI test',html=html,width=520,height=850,hidden=True)
    loaded=threading.Event();window.events.loaded+=loaded.set
    report={};errors=[]
    def run():
        try:
            if not loaded.wait(20):raise TimeoutError('WebView2 fixture did not load')
            result=window.evaluate_js('''(()=>{
              const texts=[];const walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
              while(walk.nextNode())if(!walk.currentNode.parentElement.closest('script,style'))texts.push(walk.currentNode.nodeValue);
              return {lang:document.documentElement.lang,untranslated:texts.filter(s=>/[\u3400-\u9fff]/.test(s)),
                overflow:document.documentElement.scrollWidth>innerWidth,
                buttons:[...document.querySelectorAll('button')].filter(b=>b.scrollWidth>b.clientWidth).map(b=>b.textContent)};
            })()''')
            report['popup']=result
            from System import Action
            from System.IO import MemoryStream
            from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
            holder=[];stream=MemoryStream()
            def activate_fixture():
                from System.Drawing import Point
                window.native.Opacity=0
                window.native.ShowInTaskbar=False
                window.native.Location=Point(-4000,0)
                window.native.Show()
            window.native.Invoke(Action(activate_fixture))
            window.native.Invoke(Action(lambda:holder.append(window.native.webview.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,stream))))
            assert holder[0].Wait(15000),'screenshot timed out'
            (args.output/'extension-en.png').write_bytes(bytes(stream.ToArray()));stream.Dispose()
            def render_page(name,source,css,code):
                page=re.sub(r'<script\b[^>]*>.*?</script>','',source,flags=re.S)
                page=re.sub(r'<link[^>]+>','<style>'+css+'</style>',page)
                page=page.replace('</body>','<script>'+locale+code+'</script></body>')
                loaded.clear();window.load_html(page)
                if not loaded.wait(15):raise TimeoutError(name+' did not load')
                result=window.evaluate_js('''(()=>{
                  ELTLocale.setLanguage('en');ELTLocale.translateDocument();
                  const values=[],walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
                  while(walk.nextNode())if(!walk.currentNode.parentElement.closest('script,style,[data-elt-content]'))values.push(walk.currentNode.nodeValue);
                  return {untranslated:values.filter(s=>/[\u3400-\u9fff]/.test(s)),overflow:document.documentElement.scrollWidth>innerWidth};
                })()''')
                report[name]=result;preview=[];buffer=MemoryStream()
                window.native.Invoke(Action(lambda:preview.append(window.native.webview.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,buffer))))
                assert preview[0].Wait(15000),'screenshot timed out'
                (args.output/(name+'.png')).write_bytes(bytes(buffer.ToArray()));buffer.Dispose()
            connect_code="window.fetch=async()=>({ok:true,json:async()=>({languages:{de:'德语'},defaults:{language:'de',target_language:'en',ui_language:'en',translate:true,narrate:true,lookahead:15}})});"
            connect_code+='(async()=>{'+(assets/'web/connect.js').read_text('utf-8')+'})();'
            render_page('connect-en',(assets/'web/connect.html').read_text('utf-8'),(assets/'web/style.css').read_text('utf-8'),connect_code)
            local_code="globalThis.__eltUiLanguage='en';window.fetch=async()=>({json:async()=>({name:'English test video.mp4'})});"
            local_code+=(assets/'web/local-player.js').read_text('utf-8')
            render_page('local-player-en',(assets/'web/local-player.html').read_text('utf-8'),(assets/'web/local-player.css').read_text('utf-8'),local_code)
            # Native toolbar uses the real production control builder, with
            # no service connection. Actions are never invoked in this test.
            from app.web_follow.player import Player
            from app.web_follow.toolbar import create_toolbar
            from System.Drawing import Bitmap,Size
            from System.Drawing.Imaging import ImageFormat
            from System.Windows.Forms import Form,Application,Button,CheckBox,Label,TextRenderer
            from System.Drawing import Point
            def toolbar():
                form=Form();form.ClientSize=Size(1240,700);form.Opacity=0;form.ShowInTaskbar=False;form.Location=Point(-4000,0);player=Player(window)
                player.ui=lambda action:action();player.options={'target_language':'en','ui_language':'en','tts_voice':'aiden'}
                create_toolbar(player,form,window.native.webview.CoreWebView2)
                form.Show();Application.DoEvents()
                entries=[]
                def visit(control):
                    text=str(control.Text)
                    if isinstance(control,(Button,CheckBox,Label)) and text:
                        needed=TextRenderer.MeasureText(text,control.Font).Width
                        if control.Width<needed or control.Right>control.Parent.ClientSize.Width:
                            entries.append({'text':text,'width':control.Width,'needed':needed})
                    for child in control.Controls:visit(child)
                report['toolbar']=[]
                for width in (800,1240,1600):
                    form.ClientSize=Size(width,700);form.PerformLayout();player.toolbar.PerformLayout();Application.DoEvents()
                    entries.clear();visit(player.toolbar)
                    image=Bitmap(width,player.toolbar.Height);player.toolbar.DrawToBitmap(image,player.toolbar.ClientRectangle)
                    image.Save(str(args.output/f'toolbar-en-{width}.png'),ImageFormat.Png);image.Dispose()
                    report['toolbar'].append({'width':width,'clipped':list(entries)})
                form.Dispose()
            window.native.Invoke(Action(toolbar))
        except BaseException as error:errors.append(type(error).__name__+': '+str(error))
        finally:window.destroy()
    webview.start(run,gui='edgechromium',private_mode=True,storage_path=str(args.output/'webview-test-profile'))
    report['errors']=errors
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n','utf-8');print(json.dumps(report))
    failed=bool(errors) or any(value.get('untranslated') or value.get('overflow') or value.get('buttons') for value in report.values() if isinstance(value,dict))
    failed|=any(item['clipped'] for item in report.get('toolbar',[]))
    return int(bool(failed))


if __name__=='__main__':raise SystemExit(main())
