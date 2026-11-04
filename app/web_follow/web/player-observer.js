// Observes the course clock; only its explicitly enabled volume lease is writable.
(function(){
  const local=!!globalThis.__eltLocalPlayerOrigin&&location.origin===globalThis.__eltLocalPlayerOrigin;
  if((!local&&!ELTFollow.pageAllowed(location.href))||window.__eltPlayer)return;
  const frame=crypto.randomUUID(),nonce=__ELT_NONCE__;
  const post=value=>chrome.webview.postMessage({elt:nonce,frame,...value});
  let host=null,original=null,translated=null,unlock=null,snapshot=null,seeking=false,receivedAt=0,narrationNotice='';
  const pending=new Map();let serial=0;
  const sourceVolume=new ELTFollow.SourceVolume();
  const audio=new Audio();
  audio.addEventListener('playing',()=>{narrationNotice='';post({kind:'playback',event:'playing'});});
  audio.addEventListener('ended',()=>post({kind:'playback',event:'ended'}));
  audio.addEventListener('pause',()=>post({kind:'playback',event:'paused'}));
  audio.addEventListener('error',()=>{narrationNotice='中文语音播放失败';post({kind:'playback',event:'error'});});
  const narrator=new ELTFollow.Narrator(audio,cue=>new Promise((resolve,reject)=>{
    const id=String(++serial),timer=setTimeout(()=>{pending.delete(id);reject(Error('audio timeout'));},12000);
    pending.set(id,{resolve,reject,timer});post({kind:'audio',id,name:cue.speech});
  }),reason=>{
    if(reason==='permission'){narrationNotice='请点击“允许中文朗读”';if(unlock)unlock.hidden=false;post({kind:'playback',event:'blocked'});}
    else if(reason==='unavailable'){narrationNotice='中文语音读取失败';post({kind:'playback',event:'unavailable'});}
  });
  function select(){return [...document.querySelectorAll('video')].filter(v=>Number.isFinite(v.duration)&&v.duration>0)
    .sort((a,b)=>b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight)[0];}
  function show(){
    if(host)return;host=document.createElement('div');const root=host.attachShadow({mode:'closed'});
    host.id='elt-follow-overlay';host.hidden=true;
    root.innerHTML='<style>'+ELTFollow.captionCSS+'</style>'+ELTFollow.captionMarkup;
    original=root.querySelector('#o');translated=root.querySelector('#t');
    unlock=root.querySelector('#elt-unlock');unlock.onclick=()=>{narrator.blocked=false;audio.play().then(()=>unlock.hidden=true).catch(()=>{});};
    root.querySelector('#elt-close').onclick=()=>{post({kind:'stop'});clear();};
    for(const name of ['click','pointerdown','keydown'])root.addEventListener(name,event=>event.stopPropagation());
    (document.fullscreenElement||document.body).appendChild(host);
  }
  function clear(){
    sourceVolume.command({active:false});
    narrator.cancel();snapshot=null;host?.remove();host=null;
    for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('stopped'));}pending.clear();
  }
  window.__eltPlayer={
    id:frame,
    update(value){snapshot=value;receivedAt=performance.now();show();},
    setPlayback(value){if(snapshot)snapshot.playback=value;narrator.setOptions(value);},
    mediaError(code){if(local)post({kind:'media_error',code});},
    setSourceVolume(value){
      sourceVolume.command(value);
      const display=select();
      sourceVolume.tick(display&&(ELTFollow.clockVideo?.(document.querySelectorAll('video'),display)||display));
    },
    stop:clear,
    audio(id,base64){
      const item=pending.get(id);if(!item)return;pending.delete(id);clearTimeout(item.timer);
      if(!base64){item.reject(Error('audio unavailable'));return;}
      const bytes=Uint8Array.from(atob(base64),c=>c.charCodeAt(0));
      item.resolve(URL.createObjectURL(new Blob([bytes],{type:'audio/wav'})));
    }
  };
  let bound=null;
  function tick(){
    const display=select();if(!display){sourceVolume.tick(null);return;}
    const video=ELTFollow.clockVideo?.(document.querySelectorAll('video'),display)||display;
    sourceVolume.tick(video);
    if(video!==bound){bound=video;video.addEventListener('seeking',()=>{seeking=true;if(!snapshot?.player_clock?.cross_frame)narrator.cancel();});
      video.addEventListener('pause',()=>{if(!snapshot?.player_clock?.cross_frame)audio.pause();});
      video.addEventListener('ended',()=>{if(!snapshot?.player_clock?.cross_frame)narrator.cancel();});}
    const rect=display.getBoundingClientRect(),clock={time:video.currentTime,rate:video.playbackRate,paused:video.paused,seeking:video.seeking};
    const source=local?video.currentSrc:ELTFollow.discover(video,performance.getEntriesByType('resource'));
    post({kind:'clock',source,position:clock.time,rate:clock.rate,paused:clock.paused,seek:seeking&&!video.seeking,
          area:rect.width*rect.height,page:location.href,audible:video.muted===false&&video.volume>0,
          audio_decoded:Number.isFinite(video.webkitAudioDecodedByteCount)&&video.webkitAudioDecodedByteCount>0});if(!video.seeking)seeking=false;
    if(!snapshot)return;show();
    if(snapshot.player_clock?.cross_frame){
      const master=snapshot.player_clock,age=Math.max(0,(performance.now()-receivedAt)/1000);
      clock.time=master.position+(master.paused?0:Math.min(age,1)*master.rate);
      clock.paused=master.paused||age>1;clock.rate=master.rate;clock.seeking=!!master.seeking;
    }
    const target=document.fullscreenElement||document.body;if(host.parentNode!==target)target.appendChild(host);
    ELTFollow.placeCaption(host,rect,snapshot.playback,{width:innerWidth,height:innerHeight});
    const cues=snapshot.cues||[],cue=ELTFollow.activeCue(cues,clock.time);
    ELTFollow.renderCaption(host,original,translated,unlock,cue,snapshot.playback);
    narrator.setOptions(snapshot.playback);narrator.tick(cues,clock,snapshot.session_id+':'+snapshot.generation);
  }
  setInterval(tick,200);addEventListener('pagehide',clear);
})();
