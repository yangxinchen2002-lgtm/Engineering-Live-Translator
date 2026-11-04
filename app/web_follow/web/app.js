import {activeCue} from '/sync.mjs';
const $=id=>document.getElementById(id),token=location.hash.slice(1),video=$('video');
const t=value=>globalThis.ELTLocale?.text(value)||value;
globalThis.ELTLocale?.translateDocument();
$('original').classList.add('elt-source');$('translation').classList.add('elt-translation');
let settings,hlsPlayer,pollTimer,snapshot=null,stopped=true,busy=false,epoch=0,sequence=0,seeking=false,initial=false,startAt=0;
const stats={deadlines:0,fast:0,unavailable:0};
const notice=text=>{$('notice').textContent=t(text);};
const speech=new Audio();
const narrator=new ELTFollow.Narrator(speech,async cue=>'/speech/'+cue.speech+'?token='+encodeURIComponent(token),reason=>{
  if(reason==='deadline')stats.deadlines++;
  if(reason==='fast')stats.fast++;
  if(reason==='unavailable')stats.unavailable++;
  if(reason==='permission')notice('请点击“启用朗读”允许声音；视频继续播放。');
});
async function api(path,data){
  const response=await fetch('/api/'+path,{method:data===undefined?'GET':'POST',headers:{'X-ELT-Lab-Token':token,'Content-Type':'application/json'},
    ...(data===undefined?{}:{body:JSON.stringify(data)})});
  const value=await response.json();if(!response.ok)throw Error(value.error||'实验服务不可用');return value;
}
function fill(select,options){select.replaceChildren(...options.map(([value,label])=>Object.assign(document.createElement('option'),{value,textContent:t(label)})));}
function models(){fill($('model'),settings.providers[$('provider').value].models.map(x=>[x,x]));}
function lock(locked){for(const id of ['source','language','provider','model','lookahead','translate','narrate','voice'])$(id).disabled=locked;
  if(!locked)$('narrate').disabled=!$('translate').checked||!settings?.voices.length;}
$('source').oninput=()=>{$('source').type=$('source').value.includes('?')?'password':'text';};
function render(){
  if(stopped||!snapshot)return;
  const clock={time:video.currentTime||0,rate:video.playbackRate,paused:video.paused,seeking:video.seeking||seeking};
  const cues=clock.seeking?[]:snapshot.cues,cue=activeCue(cues,clock.time);
  $('original').textContent=cue?.source||'';$('translation').textContent=cue?.translation||'';
  ELTFollow.fitCaption($('original'),19,10);ELTFollow.fitCaption($('translation'),22,10);
  $('original').dataset.start=cue?.start??'';$('original').dataset.end=cue?.end??'';
  narrator.setOptions(snapshot.playback);
  narrator.tick(cues,clock,snapshot.session_id+':'+snapshot.generation);
  const behind=snapshot.prepared_until<clock.time;
  $('status').textContent=t(snapshot.status==='error'?'预读出错，视频继续播放':cue?.boundary==='pending'?'结合后续音频确认整句，视频继续播放':behind?'字幕准备中，视频继续播放':video.paused?'已暂停（用户控制）':'整句朗读 · 按视频时间跟随');
  if(snapshot.error)notice(snapshot.error+'；视频不会自动暂停。');
  else if(cue?.translation_error||cue?.speech_error)notice(cue.translation_error||cue.speech_error);
  const s=Math.floor(clock.time),ahead=Math.max(0,snapshot.prepared_until-clock.time);
  $('clock').textContent=`${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')} / ${t('预读')} ${ahead.toFixed(1)} ${t('秒')}`;
  $('progress').value=ahead;$('progress').max=Number($('lookahead').value);
  $('diagnostics').textContent=JSON.stringify({player_time:clock.time,mode:'user_controlled',cue_range:cue?[cue.start,cue.end]:null,
    revision:snapshot.generation,ahead_seconds:ahead,speech_rate:speech.playbackRate,speaking:!speech.paused,
    speech_deadlines:stats.deadlines,excessive_speed:stats.fast,speech_unavailable:stats.unavailable,
    metrics:snapshot.metrics,input:snapshot.metadata},null,2);
}
async function heartbeat(seek=false){
  if(stopped||busy&&!seek||seeking&&!seek||initial&&Math.abs(video.currentTime-startAt)>.15)return;
  busy=true;const current=epoch,seq=++sequence;
  try{
    const s=await api('clock',{position:video.currentTime||0,paused:video.paused,rate:video.playbackRate,seek,sequence:seq,session_id:snapshot?.session_id});
    if(current===epoch&&seq===sequence&&!stopped){snapshot=s;render();}
  }catch(e){if(current===epoch){narrator.cancel();notice(e.message+'；视频继续播放。');}}
  finally{if(seq===sequence)busy=false;}
}
$('prepare').onclick=async()=>{
  $('prepare').disabled=true;stopped=true;epoch++;narrator.cancel();snapshot=null;busy=false;
  try{
    startAt=Number($('startAt').value)||0;initial=startAt>0;
    snapshot=await api('start',{source:$('source').value,language:$('language').value,position:startAt,lookahead:Number($('lookahead').value),
      provider:$('provider').value,model:$('model').value,translate:$('translate').checked,narrate:$('narrate').checked,voice:Number($('voice').value),
      target_language:settings.defaults?.target_language||'zh',ui_language:settings.defaults?.ui_language||'zh'});
    stopped=false;seeking=false;lock(true);stats.deadlines=stats.fast=stats.unavailable=0;
    if(hlsPlayer){hlsPlayer.destroy();hlsPlayer=null;}
    const url='/media?token='+encodeURIComponent(token);
    if(/\.m3u8(?:\?|$)/i.test($('source').value)&&window.Hls?.isSupported()){
      hlsPlayer=new Hls({maxBufferLength:30,maxMaxBufferLength:60,enableWorker:true});hlsPlayer.loadSource(url);hlsPlayer.attachMedia(video);
    }else{video.src=url;video.load();}
    $('play').disabled=$('pause').disabled=$('stop').disabled=$('jump').disabled=false;
    notice('视频完全由你控制。ELT 不会因字幕、翻译或朗读自动暂停视频。');
    clearInterval(pollTimer);pollTimer=setInterval(heartbeat,300);heartbeat();
  }catch(e){notice(e.message);$('prepare').disabled=false;lock(false);}
};
// Video mutations below are explicit user controls only; render/network code never controls playback.
$('play').onclick=()=>video.play().catch(()=>notice('请使用视频自身的播放按钮。'));
$('pause').onclick=()=>video.pause();
$('jump').onclick=()=>{const at=Number($('startAt').value);if(Number.isFinite(at)&&at>=0&&at<video.duration)video.currentTime=at;else notice('请输入视频时长范围内的位置。');};
$('videoRate').onchange=()=>{video.playbackRate=Number($('videoRate').value);};
$('enableSpeech').onclick=()=>{narrator.blocked=false;narrator.finished.clear();render();};
async function stop(){
  stopped=true;epoch++;clearInterval(pollTimer);narrator.cancel();
  await api('stop',{});lock(false);$('prepare').disabled=false;
  $('stop').disabled=$('jump').disabled=true;snapshot=null;
  $('status').textContent=t('ELT 已停止；视频由你控制');$('original').textContent=$('translation').textContent='';
}
$('stop').onclick=()=>stop().catch(e=>notice(e.message));
$('quit').onclick=async()=>{try{await stop();await api('quit',{});notice('实验服务已关闭。');}catch(e){notice(e.message);}};
video.addEventListener('pause',()=>speech.pause());
video.addEventListener('seeking',()=>{if(stopped)return;seeking=true;narrator.cancel();if(snapshot)snapshot.cues=[];$('original').textContent=$('translation').textContent='';});
video.addEventListener('seeked',async()=>{if(stopped)return;await heartbeat(!initial);initial=false;seeking=false;});
video.addEventListener('loadedmetadata',()=>{if(initial&&!stopped)video.currentTime=startAt;});
video.addEventListener('ended',()=>narrator.cancel());
$('translate').onchange=()=>{$('narrate').disabled=!$('translate').checked;if(!$('translate').checked)$('narrate').checked=false;};
$('pairBridge').onclick=()=>{if(!$('pairBridge').dataset.extensionReady)notice('请先在 Edge 加载 experiments/lookahead/extension 扩展，然后刷新本页。');};
addEventListener('pagehide',()=>{narrator.cancel();if(!stopped)fetch('/api/stop',{method:'POST',keepalive:true,headers:{'X-ELT-Lab-Token':token},body:'{}'}).catch(()=>{});});
const lifetime=setInterval(()=>api('ping',{}).catch(()=>clearInterval(lifetime)),10000);
const bridgeMonitor=setInterval(async()=>{
  try{const b=await api('bridge-status');
    if(b.active){const s=await api('state');$('bridgeInfo').textContent=s.error?'预读错误：'+s.error:
      `已跟随原网页：${s.position.toFixed(1)} 秒 · 已预读至 ${s.prepared_until.toFixed(1)} 秒 · 字幕 ${s.cues.length} 条`;}
    else $('bridgeInfo').textContent=t(b.paired?'已配对，请在课程页点击扩展开始跟随':'等待配对');
    globalThis.ELTLocale?.translateDocument();
  }catch{clearInterval(bridgeMonitor);}
},1000);
try{
  settings=await api('settings');globalThis.ELTLocale?.setLanguage(settings.defaults?.ui_language||'zh');globalThis.ELTLocale?.translateDocument();
  fill($('language'),Object.entries(settings.languages));
  fill($('provider'),Object.entries(settings.providers).map(([id,p])=>[id,p.label]));models();$('provider').onchange=models;
  fill($('voice'),settings.voices.map(v=>[v.id,v.label]));
  const d=settings.defaults||{};
  if(d.provider){$('provider').value=d.provider;models();$('model').value=d.model;}
  if(d.language)$('language').value=d.language;
  if(d.voice!=null)$('voice').value=d.voice;
  if(d.lookahead)$('lookahead').value=d.lookahead;
  $('translate').checked=!!d.translate;$('narrate').checked=!!d.narrate;$('narrate').disabled=!d.translate;
}catch(e){notice(e.message);$('prepare').disabled=true;}
function tick(){render();requestAnimationFrame(tick);}tick();
