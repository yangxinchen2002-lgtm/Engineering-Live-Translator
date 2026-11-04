"""ELT's internal WebView2 course window. Launched and owned by the main GUI."""
from __future__ import annotations
from app.i18n import tr as _tr
import base64
import json
import os
from pathlib import Path
import queue
import re
import secrets
import sys
import threading
import time
from urllib.parse import urlsplit

from .bridge import validate_media
from .timeline import finite
from app.ui.lifetime import JOB_ENV,join_owner_job

HERE=Path(__file__).with_name('web')
PAGE_HOSTS={'live.rbg.tum.de','www.moodle.tum.de','moodle.tum.de','video.opencast.tum.de'}
WELCOME='''<html lang="zh-CN"><meta charset="utf-8"><style>body{font:18px/1.7 "Segoe UI",sans-serif;background:#f4f6fa;color:#21314a;margin:8%}h1{color:#405cf3}section{background:white;padding:36px;border-radius:20px}</style><section><h1>ELT · 课程播放</h1><p>点击上方“本地视频”选择文件，或打开 TUM-Live / Moodle 课程网页。</p><p>语言、翻译和朗读沿用主界面设置。打开视频后点击“开始字幕”即可预读；可先等待字幕准备，再使用视频自己的播放按钮。</p><p>网页课程首次使用可在此窗口登录。视频播放、暂停、跳转和倍速由你控制；停止字幕后视频仍可继续播放。关闭本窗口会结束当前视频。</p></section></html>'''


def service_address(value):
    u=urlsplit(value)
    if (u.scheme!='http' or u.hostname!='127.0.0.1' or not u.port or u.username or u.password
            or u.path not in ('','/') or u.query or not re.fullmatch('[A-Za-z0-9_-]{32,80}',u.fragment)):
        raise ValueError('invalid local service')
    return f'http://127.0.0.1:{u.port}',u.fragment


def configure_audio_playback():
    # Process-local WebView2 behavior for this audio application, not Edge policy.
    key='WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS';arguments=os.environ.get(key,'')
    if '--autoplay-policy=' not in arguments:
        os.environ[key]=(arguments+' --autoplay-policy=no-user-gesture-required').strip()


def observation(value,local_host=None):
    if not isinstance(value,dict):raise ValueError('invalid video observation')
    page=urlsplit(value.get('page',''))
    local=local_host is not None and local_host.is_page(value.get('page',''))
    if not local and (page.scheme!='https' or page.hostname not in PAGE_HOSTS or page.username or page.password):
        raise ValueError('unsupported course frame')
    selected=local_host.source_for(value['source']) if local and value.get('source') else None
    source=selected.value if selected else validate_media(value['source']) if value.get('source') else ''
    if type(value.get('paused')) is not bool or type(value.get('seek')) is not bool:raise ValueError('invalid clock flags')
    return dict(source=source,position=finite(value.get('position'),0,86399),rate=finite(value.get('rate'),.25,4),
                paused=value['paused'],seek=value['seek'],area=finite(value.get('area'),0,1e8),
                audible=value.get('audible') is True,audio_decoded=value.get('audio_decoded') is True,
                source_identity=list(selected.local_identity) if selected else None)


def player_frames(candidates,previous_clock=None):
    """Render on the largest picture; time follows the actual soundtrack."""
    display=max(candidates,key=lambda item:item[1][2]['area'])
    audible=[item for item in candidates if item[1][2].get('audible')]
    decoded=[item for item in (audible or candidates) if item[1][2].get('audio_decoded')]
    previous=next((item for item in candidates if item[0]==previous_clock),None)
    if len(audible)==1:clock=audible[0]
    elif len(decoded)==1:clock=decoded[0]
    else:clock=previous or display
    return clock,display


class Player:
    def __init__(self,window):
        self.window=window;self.nonce=secrets.token_hex(24);self.commands=queue.Queue(maxsize=16)
        self.exit=threading.Event();self.lock=threading.Lock();self.frames={};self.handles={};self.installed=False
        self.target=None;self.client=None;self.options={};self.following=False;self.source_key='';self.active_frame=None;self.clock_frame=None
        self.core=None;self.status=None;self.thread=None
        self.reading_controls=None;self.caption_controls=None;self.setting_controls=False;self.pending_playback={}
        self.playback_counts={k:0 for k in ('audio_requests','audio_fetched','audio_fetch_failed','playing','ended','blocked','audio_errors')}
        self.audio_active=False
        self.local_host=None;self.local_error_reported=False
        self.source_volume_frame=None
        self.system_voices=[];self.voice_values=[]
        self.reading_models=[('qwen','0.6B',_tr('本地 0.6B · 快速')),('qwen','1.7B',_tr('本地 1.7B · 讲课')),('system',None,_tr('Windows 系统音色'))]

    def enqueue(self,command,**data):
        try:self.commands.put_nowait(dict(command=command,**data))
        except queue.Full:self.notice(_tr('操作过于频繁，请稍后再试。'))

    def ui(self,action):
        from System import Action
        try:self.window.native.BeginInvoke(Action(action))
        except Exception:pass  # A closed window no longer accepts UI updates.

    def notice(self,text):
        if self.status:self.ui(lambda:setattr(self.status,'Text',_tr(text)))

    def change_playback(self,key,value):
        if self.setting_controls:return
        with self.lock:self.pending_playback[key]=value

    def open_local_file(self):
        from System.Windows.Forms import OpenFileDialog,DialogResult
        dialog=OpenFileDialog();dialog.Title=_tr('选择本地课程视频')
        dialog.Filter=_tr('视频文件|*.mp4;*.m4v;*.webm;*.mov|音频文件|*.mp3;*.wav;*.m4a;*.ogg|所有文件|*.*')
        dialog.CheckFileExists=True;dialog.Multiselect=False;dialog.RestoreDirectory=True
        try:
            if dialog.ShowDialog(self.window.native)==DialogResult.OK:self.enqueue('LOCAL_FILE',path=str(dialog.FileName))
        finally:dialog.Dispose()

    def open_local(self,path):
        if self.local_host is None:
            from .local_media import LocalMediaHost
            self.local_host=LocalMediaHost()
        url=self.local_host.select(path);self.local_error_reported=False
        self.ui(lambda:self.core.Navigate(url))
        self.notice(_tr('本地视频已打开；点击“开始字幕”准备字幕，视频由你控制。'))

    def close_local(self):
        if self.local_host:self.local_host.close();self.local_host=None

    def update_reading_controls(self):
        values=dict(self.options)
        def apply():
            if not self.reading_controls:return
            from System import Decimal
            from System.Globalization import CultureInfo
            check,speed,volume,amount,model,voice,duck,source_percent=self.reading_controls
            self.setting_controls=True
            try:
                check.Checked=bool(values.get('narrate',False))
                speed.Value=Decimal.Parse(str(values.get('base_speed',1)),CultureInfo.InvariantCulture)
                volume.Value=int(values.get('volume',80));amount.Text=str(volume.Value)+'%'
                duck.Checked=values.get('duck_source',True);source_percent.Value=Decimal(int(values.get('source_percent',20)))
                selected=next((i for i,(engine,size,_) in enumerate(self.reading_models) if engine==values.get('speech_engine','qwen') and
                    (engine=='system' or size==values.get('tts_model','0.6B'))),0)
                model.SelectedIndex=selected
                if values.get('speech_engine')=='system':
                    self.voice_values=[(v['id'],v['label']) for v in self.system_voices];wanted=values.get('voice',0)
                else:
                    from app.speech.config import VOICES
                    self.voice_values=list(VOICES);wanted=values.get('tts_voice','serena')
                voice.Items.Clear()
                for _,label in self.voice_values:voice.Items.Add(_tr(label))
                voice.SelectedIndex=next((i for i,(key,_) in enumerate(self.voice_values) if key==wanted),0 if self.voice_values else -1)
                if self.voice_values:
                    from System.Windows.Forms import TextRenderer
                    voice.DropDownWidth=max(voice.Width,min(600,max(TextRenderer.MeasureText(label,voice.Font).Width for _,label in self.voice_values)+40))
                    self.tooltips.SetToolTip(voice,_tr(self.voice_values[voice.SelectedIndex][1]) if voice.SelectedIndex>=0 else _tr('选择朗读音色'))
                for control in (check,speed,volume,model):control.Enabled=self.client is not None
                duck.Enabled=self.client is not None;source_percent.Enabled=self.client is not None and duck.Checked
                voice.Enabled=self.client is not None and bool(self.voice_values)
                if self.caption_controls:
                    for key,control in self.caption_controls.items():
                        control.Value=Decimal(int(values.get(key,{'caption_width':92,'caption_height':180,'caption_font_size':18}[key])))
                        control.Enabled=self.client is not None
            finally:self.setting_controls=False
        self.ui(apply)

    def reading_status(self,snapshot):
        if not self.options.get('narrate'):return _tr('译文朗读已关闭')
        counts=self.playback_counts;tts=snapshot.get('metrics',{}).get('tts',{})
        if counts['blocked']:return _tr('请点击字幕上的“允许译文朗读”')
        if counts['audio_fetch_failed'] and not counts['playing']:return _tr('语音读取失败，请查看朗读诊断')
        if tts.get('status')=='error':return _tr('译文朗读暂不可用（')+str(tts.get('error_code',_tr('生成失败')))+'）'
        if tts.get('status')=='loading':return _tr('译文朗读模型准备中')
        if self.audio_active:return _tr('正在朗读中文')
        return _tr('译文朗读已就绪') if tts.get('generated') or counts['audio_fetched'] else _tr('等待中文语音')

    def execute(self,frame,code,identity=None):
        if identity is not None:code='if(window.__eltPlayer?.id==='+json.dumps(identity)+'){'+code+';}'
        def run():
            try:frame.ExecuteScriptAsync(code)
            except Exception:pass  # A navigated/destroyed frame cannot render an old result.
        self.ui(run)

    def stop_render(self):
        self.audio_active=False
        self.sync_source_volume(force_off=True)
        with self.lock:frames=[v[1] for v in self.frames.values()]
        for frame in frames:self.execute(frame,'window.__eltPlayer?.stop()')

    def sync_source_volume(self,force_off=False):
        """Duck only the actual soundtrack frame, not the Chinese Audio output."""
        with self.lock:
            row=self.frames.get(self.clock_frame)
            active=(not force_off and self.following and self.client is not None and self.audio_active
                    and self.options.get('narrate',False) and self.options.get('duck_source',True)
                    and row is not None and time.monotonic()-row[0]<2 and not row[2]['paused'])
            target=(self.clock_frame,row[1]) if active else None
            previous=self.source_volume_frame;self.source_volume_frame=target
        if previous and (target is None or previous[0]!=target[0]):
            self.execute(previous[1],'window.__eltPlayer?.setSourceVolume({active:false})',previous[0])
        if target:
            value={'active':True,'percent':self.options.get('source_percent',20)}
            self.execute(target[1],'window.__eltPlayer?.setSourceVolume('+json.dumps(value)+')',target[0])

    def message(self,sender,args):
        try:
            raw=str(args.WebMessageAsJson)
            if len(raw)>16384:return
            data=json.loads(raw)
            if not isinstance(data,dict) or data.get('elt')!=self.nonce:return
            source=urlsplit(str(args.Source))
            local=self.local_host is not None and self.local_host.is_page(str(args.Source))
            if not local and (source.scheme!='https' or source.hostname not in PAGE_HOSTS):return
            identity=data.get('frame')
            if not isinstance(identity,str) or not re.fullmatch('[a-f0-9-]{36}',identity):return
            if data.get('kind')=='clock':
                try:value=observation(data,self.local_host if local else None)
                except (ValueError,OSError):
                    if local and not self.local_error_reported:
                        self.local_error_reported=True;self.enqueue('LOCAL_ERROR',code='file_unavailable')
                    return
                with self.lock:
                    if identity not in self.frames and len(self.frames)>=16:self.frames.pop(next(iter(self.frames)))
                    previous=self.frames.get(identity)
                    if previous and previous[2].get('seek'):value['seek']=True
                    self.frames[identity]=(time.monotonic(),sender,value)
            elif data.get('kind')=='media_error' and local and not self.local_error_reported:
                self.local_error_reported=True;self.enqueue('LOCAL_ERROR',code='playback_failed')
            elif data.get('kind')=='stop' and identity==self.active_frame:
                self.enqueue('STOP')
            elif data.get('kind')=='audio' and identity==self.active_frame:
                if (isinstance(data.get('name'),str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}\.wav',data['name'])
                        and re.fullmatch('[0-9]{1,8}',str(data.get('id','')))):
                    with self.lock:self.playback_counts['audio_requests']+=1
                    self.enqueue('AUDIO',frame=sender,frame_id=identity,id=data['id'],name=data['name'])
            elif data.get('kind')=='playback' and identity==self.active_frame:
                if data.get('event')=='playing':self.audio_active=True
                elif data.get('event') in ('ended','paused','error','blocked'):self.audio_active=False
                key={'playing':'playing','ended':'ended','blocked':'blocked','error':'audio_errors','unavailable':'audio_errors'}.get(data.get('event'))
                if key:
                    with self.lock:
                        self.playback_counts[key]+=1
                        if key=='playing':self.playback_counts['blocked']=0
                self.sync_source_volume()
        except (ValueError,TypeError,KeyError,AttributeError):return

    def frame_created(self,sender,args):
        frame=args.Frame
        if len(self.handles)>=32:return
        key=id(frame)
        handler=lambda s,e:self.message(frame,e)
        self.handles[key]=(frame,handler)
        frame.WebMessageReceived+=handler
        frame.Destroyed+=lambda s,e:self.handles.pop(key,None)

    def install(self):
        if self.installed:return
        from System.Windows.Forms import Label,DockStyle
        from System.Drawing import Color,Font,Icon
        form=self.window.native;core=form.webview.CoreWebView2
        if core is None:return
        self.installed=True;self.core=core
        if self.local_host is None:
            from .local_media import LocalMediaHost
            self.local_host=LocalMediaHost()
        # Keep pywebview's own array-based RPC, route our object messages separately.
        form.webview.WebMessageReceived-=form.browser.on_script_notify
        def library_message(sender,args):
            if str(args.WebMessageAsJson).startswith('['):form.browser.on_script_notify(sender,args)
        form.webview.WebMessageReceived+=library_message
        form.Icon=Icon(str(Path(__file__).parents[1]/'ui/assets/elt.ico'))
        core.Settings.IsPasswordAutosaveEnabled=False;core.Settings.IsGeneralAutofillEnabled=False
        core.WebMessageReceived+=self.message;core.FrameCreated+=self.frame_created
        def permissions(s,args):
            from Microsoft.Web.WebView2.Core import CoreWebView2PermissionState
            uri=urlsplit(str(args.Uri));kind=str(args.PermissionKind).lower()
            args.State=(CoreWebView2PermissionState.Allow if kind=='autoplay' and ((uri.scheme=='https' and uri.hostname in PAGE_HOSTS) or self.local_host.is_page(str(args.Uri)))
                        else CoreWebView2PermissionState.Deny)
        core.PermissionRequested+=permissions
        def navigation(s,args):
            if urlsplit(str(args.Uri)).scheme not in ('https','about') and not self.local_host.is_page(str(args.Uri)):args.Cancel=True
            self.enqueue('NAVIGATE')
        core.NavigationStarting+=navigation
        script='\n'.join((HERE/name).read_text(encoding='utf-8') for name in ('../extension/core.js','../extension/layout.js','../extension/source-volume.js','../extension/ui-locale.js','player-observer.js'))
        from app.i18n import get_language
        script='globalThis.__eltUiLanguage='+json.dumps(get_language())+';\n'+script
        script='globalThis.__eltLocalPlayerOrigin='+json.dumps(self.local_host.origin)+';\n'+script
        core.AddScriptToExecuteOnDocumentCreatedAsync(script.replace('__ELT_NONCE__',json.dumps(self.nonce)))
        from .toolbar import create_toolbar
        address=create_toolbar(self,form,core)
        self.status=Label();self.status.Dock=DockStyle.Bottom;self.status.Height=30
        self.status.Text=_tr('ELT 课程窗口 · 请打开课程；首次使用可在本窗口登录')
        self.status.Font=Font('Microsoft YaHei UI',9);self.status.ForeColor=Color.FromArgb(105,122,148)
        self.status.BackColor=Color.FromArgb(244,246,250)
        form.Controls.Add(self.status);self.status.BringToFront()
        core.SourceChanged+=lambda s,e:setattr(address,'Text',_tr('本地视频 · ')+self.local_host.name if self.local_host.is_page(str(core.Source)) else str(core.Source))
        print(json.dumps({'event':'player_ready'}),flush=True)

    def _request(self,path,data=None):
        response=self.client.request('GET' if data is None else 'POST',path,json=data)
        response.raise_for_status();return response

    def _stop(self):
        self.following=False;self.source_key='';self.active_frame=None;self.clock_frame=None;self.stop_render()
        if self.client:
            try:self._request('/api/stop',{})
            except Exception:pass  # Disconnected service is already unable to produce more audio.

    def loop(self):
        import httpx
        try:
            while not self.exit.wait(.15):
                try:
                    try:command=self.commands.get_nowait()
                    except queue.Empty:command={}
                    kind=command.get('command')
                    if kind in ('CONFIG','CONNECT'):
                        self._stop()
                        if self.client:self.client.close();self.client=None
                        if command.get('url'):
                            origin,token=service_address(command['url']);self.client=httpx.Client(base_url=origin,
                                headers={'X-ELT-Lab-Token':token},trust_env=False,timeout=5)
                            settings=self._request('/api/settings').json();self.options=settings['defaults'];self.system_voices=settings.get('voices',[])
                            self.following=True
                            self.update_reading_controls()
                            self.notice(_tr('已连接 ELT 主程序，自动等待并跟随当前课程视频。'))
                    elif kind in ('STOP','NAVIGATE','DISCONNECT'):
                        resume=self.following and kind=='NAVIGATE'
                        self._stop()
                        if kind=='NAVIGATE':
                            with self.lock:self.frames.clear()
                            self.following=resume
                        self.notice(_tr('自动等待新课程视频') if resume else _tr('字幕已停止；视频由原播放器继续控制。'))
                        if kind=='DISCONNECT' and self.client:self.client.close();self.client=None
                    elif kind=='CLOSE':self.window.destroy();break
                    elif kind=='RAISE':self.window.show();self.window.restore()
                    elif kind=='PICK_LOCAL':self.ui(self.open_local_file)
                    elif kind=='LOCAL_FILE':
                        try:self.open_local(command['path'])
                        except (OSError,ValueError):self.notice(_tr('无法打开所选文件，请检查格式、文件位置和读取权限。'))
                    elif kind=='LOCAL_ERROR':
                        self._stop()
                        self.notice(_tr('本地视频无法读取或编码不受支持；请重新打开文件，推荐 H.264 / AAC 的 MP4。'))
                    elif kind=='FOLLOW':
                        if self.client:self.following=True
                        else:
                            print(json.dumps({'event':'player_follow_requested'}),flush=True)
                            self.notice(_tr('正在请求主程序启动视频预读…'))
                    elif kind=='AUDIO' and self.client:
                        encoded=''
                        try:
                            response=self._request('/speech/'+command['name'])
                            if len(response.content)>2_097_152:raise ValueError('audio limit')
                            encoded=base64.b64encode(response.content).decode('ascii')
                            with self.lock:self.playback_counts['audio_fetched']+=1
                        finally:
                            if not encoded:
                                with self.lock:self.playback_counts['audio_fetch_failed']+=1
                            self.execute(command['frame'],'window.__eltPlayer?.audio('+json.dumps(command['id'])+','+json.dumps(encoded)+')',command['frame_id'])
                    with self.lock:
                        reading=dict(self.pending_playback);self.pending_playback.clear()
                    if reading and self.client:
                        try:
                            updated=self._request('/api/playback',reading).json()
                            self.options.update(updated.get('playback',{}));self.update_reading_controls()
                            self.sync_source_volume()
                            with self.lock:frames=list(self.frames.items())
                            for fid,(_,target,_) in frames:self.execute(target,'window.__eltPlayer?.setPlayback('+json.dumps(self.options)+')',fid)
                        except Exception:
                            self.update_reading_controls();self.notice(_tr('朗读设置未应用，请确认已启用中文翻译。'))
                    if not self.following or not self.client:continue
                    with self.lock:
                        candidates=[(k,v) for k,v in self.frames.items() if time.monotonic()-v[0]<2 and v[2]['source']]
                    if not candidates:
                        self.sync_source_volume(force_off=True)
                        self.notice(_tr('等待视频；可打开 TUM 课程，或点击“本地视频”选择文件。'));continue
                    selected,display=player_frames(candidates,self.clock_frame)
                    render_identity,(_,render_frame,render_value)=display
                    identity,(observed_at,frame,value)=selected
                    self.clock_frame=identity
                    media=urlsplit(value['source']);key=identity+media.netloc+media.path
                    if key!=self.source_key:
                        self.stop_render()
                        snapshot=self._request('/api/start',{**self.options,'source':value['source'],'position':value['position'],
                            'source_identity':value.get('source_identity')}).json()
                        self.source_key=key
                    else:
                        with self.lock:playback=dict(self.playback_counts)
                        snapshot=self._request('/api/clock',{**{k:value[k] for k in ('position','rate','paused','seek')},'playback':playback}).json()
                    if self.active_frame is not None and self.active_frame!=render_identity:self.stop_render()
                    self.active_frame=render_identity
                    self.sync_source_volume()
                    if not snapshot.get('has_source'):
                        self.following=False;self.source_key='';self.stop_render()
                        self.notice(_tr('本轮字幕会话已停止；需要时点击“开始字幕”。'));continue
                    with self.lock:
                        if identity in self.frames and self.frames[identity][0]==observed_at:self.frames[identity][2]['seek']=False
                    if identity!=render_identity:
                        with self.lock:latest=self.frames.get(identity)
                        if latest:observed_at,_,value=latest
                        age=min(2,max(0,time.monotonic()-observed_at))
                        snapshot['player_clock']=dict(cross_frame=True,position=value['position']+(0 if value['paused'] else age*value['rate']),
                                                      paused=value['paused'],rate=value['rate'],seeking=value['seek'])
                    self.execute(render_frame,'window.__eltPlayer?.update('+json.dumps(snapshot,ensure_ascii=True)+')',render_identity)
                    self.notice(_tr('字幕跟随中 · ')+(snapshot.get('error') or _tr('模型准备中') if snapshot['status']=='loading' else snapshot.get('error') or self.reading_status(snapshot)))
                except Exception:
                    self.sync_source_volume(force_off=True)
                    self.notice(_tr('网页跟随连接暂不可用；视频继续播放，请检查 ELT 主界面。'))
        finally:
            self._stop()
            if self.client:self.client.close();self.client=None


def main():
    join_owner_job(os.environ.get(JOB_ENV,''))
    configure_audio_playback()
    import webview
    from app.ui.preferences import default_path
    webview.settings['ALLOW_FILE_URLS']=False
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER']=False
    window=webview.create_window(_tr('ELT · 课程播放'),html=_tr(WELCOME),width=1240,height=900,min_size=(800,600))
    player=Player(window)
    window.events.loaded+=lambda:player.ui(player.install)
    window.events.closed+=lambda:player.exit.set()
    def control():
        import msvcrt,win32file,win32pipe
        handle=msvcrt.get_osfhandle(sys.stdin.fileno());buffer=b''
        while not player.exit.wait(.05):
            try:
                _,available,_=win32pipe.PeekNamedPipe(handle,0)
                if not available:continue
                _,chunk=win32file.ReadFile(handle,min(available,4096));buffer+=chunk
                if len(buffer)>32768:raise ValueError('command size limit')
                while b'\n' in buffer:
                    raw,buffer=buffer.split(b'\n',1);value=json.loads(raw)
                    if value.get('command') not in ('CONFIG','CONNECT','RAISE','DISCONNECT','CLOSE','PICK_LOCAL'):continue
                    player.enqueue(**value)
                    if value['command']=='CLOSE':return
            except Exception:player.enqueue('CLOSE');return
    def started():
        player.control_thread=threading.Thread(target=control,daemon=True);player.control_thread.start()
        player.thread=threading.Thread(target=player.loop,daemon=True);player.thread.start()
    try:webview.start(started,gui='edgechromium',private_mode=False,storage_path=str(default_path().parent/'course-browser'))
    finally:
        player.exit.set()
        if player.thread:player.thread.join(timeout=10)
        if hasattr(player,'control_thread'):player.control_thread.join(timeout=1)
        player.close_local()


if __name__=='__main__':main()
