(()=>{
  'use strict';if(globalThis.__eltFollowInstalled)return;globalThis.__eltFollowInstalled=true;
  let owner='',video=null,snapshot=null,busy=false,started=false,sequence=0,seekPending=false,epoch=0;
  let host=null,original,translated,unlock,observer,mediaKey='',lastPosition=null,connectionError=false;
  let unbind=()=>{},invalidated=false,stopButton=null;
  let picture=null,registeredDocument='',duckLease='',narrating=false,narrationSerial=0;
  const sourceVolume=new ELTFollow.SourceVolume();
  const timers=[];
  const audio=new Audio();const stats={late:0,fast:0,unavailable:0};
  function voicePlaying(value){
    narrating=value;narrationSerial++;
    if(owner)send({kind:'ELT_DUCK',playing:value,narration_serial:narrationSerial}).catch(()=>{});
  }
  audio.addEventListener('playing',()=>voicePlaying(true));
  for(const name of ['pause','ended','error'])audio.addEventListener(name,()=>voicePlaying(false));
  const runtime=chrome.runtime,messenger=ELTRuntime.createMessenger(runtime,invalidate);
  const send=data=>messenger.send({...data,owner});
  const narrator=new ELTFollow.Narrator(audio,async cue=>{
    const result=await send({kind:'ELT_AUDIO',name:cue.speech});if(result?.error||!result?.audio)throw Error('speech unavailable');
    const binary=atob(result.audio),bytes=Uint8Array.from(binary,c=>c.charCodeAt(0));
    return URL.createObjectURL(new Blob([bytes],{type:'audio/wav'}));
  },reason=>{
    if(reason==='deadline')stats.late++;
    if(reason==='fast')stats.fast++;
    if(reason==='unavailable')stats.unavailable++;
    if(reason==='permission')unlock.hidden=false;
  });
  function selectVideo(){return [...document.querySelectorAll('video')].sort((a,b)=>{
    const x=a.getBoundingClientRect(),y=b.getBoundingClientRect();return y.width*y.height-x.width*x.height;
  })[0]||null;}
  function register(){
    if(invalidated)return;
    const display=selectVideo(),v=display&&(ELTFollow.clockVideo(document.querySelectorAll('video'),display)),r=display?.getBoundingClientRect();
    send({kind:'ELT_REGISTER',area:r?r.width*r.height:0,audible:v?.muted===false&&v.volume>0,
      audio_decoded:Number.isFinite(v?.webkitAudioDecodedByteCount)&&v.webkitAudioDecodedByteCount>0})
      .then(result=>{if(result?.document_id)registeredDocument=result.document_id;}).catch(()=>{});
  }
  function show(){
    if(host)return;host=document.createElement('div');host.id='elt-follow-overlay';
    const root=host.attachShadow({mode:'closed'});
    host.hidden=true;root.innerHTML='<style>'+ELTFollow.captionCSS+'</style>'+ELTFollow.captionMarkup;
    original=root.querySelector('#o');translated=root.querySelector('#t');
    const stop=root.querySelector('#elt-close');stop.onclick=event=>{event.stopPropagation();send({kind:'ELT_STOP'}).catch(()=>{});deactivate();};
    stopButton=stop;
    unlock=root.querySelector('#elt-unlock');unlock.onclick=event=>{event.stopPropagation();narrator.blocked=false;narrator.finished.clear();unlock.hidden=true;tick();};
    for(const name of ['click','pointerdown','keydown'])root.addEventListener(name,event=>event.stopPropagation());
    (document.fullscreenElement||document.body||document.documentElement).append(host);
  }
  function place(){
    if(!host||!video)return;const r=(picture||video).getBoundingClientRect();
    const container=document.fullscreenElement||document.body||document.documentElement;
    if(host.parentElement!==container)container.append(host);
    ELTFollow.placeCaption(host,r,snapshot?.playback,{width:innerWidth,height:innerHeight});
  }
  function bind(v){
    video=v;seekPending=true;
    const listen=(name,fn)=>{v.addEventListener(name,fn);return()=>v.removeEventListener(name,fn);};
    const releases=[listen('seeking',()=>{seekPending=true;narrator.cancel();snapshot=null;}),
      listen('pause',()=>audio.pause()),listen('ended',()=>narrator.cancel()),listen('ratechange',tick)];
    return()=>releases.forEach(fn=>fn());
  }
  function deactivate(){
    epoch++;owner='';started=false;busy=false;snapshot=null;mediaKey='';lastPosition=null;
    sourceVolume.command({active:false});duckLease='';narrating=false;narrationSerial++;
    narrator.cancel();unbind();host?.remove();host=null;connectionError='';
  }
  function invalidate(){
    if(invalidated)return;
    invalidated=true;
    for(const timer of timers)clearInterval(timer);
    removeEventListener('pagehide',onPageHide);
    deactivate();
  }
  async function heartbeat(){
    if(!owner||busy)return;
    show();picture=selectVideo();const v=picture&&ELTFollow.clockVideo(document.querySelectorAll('video'),picture);if(!v||!Number.isFinite(v.duration)||v.duration<=0){return {error:'请在原网页点击播放，正在等待视频元素。',error_code:'PAGE_NOT_READY'};}
    if(v!==video){unbind();unbind=bind(v);}
    if(started&&v.seeking)return;
    const source=ELTFollow.discover(v,performance.getEntriesByType('resource'));
    if(!source){return {error:'尚未发现可预读媒体；可刷新课程页后再开始。原视频保持正常播放。',error_code:'PAGE_NOT_READY'};}
    const key=new URL(source).origin+new URL(source).pathname;
    busy=true;const currentEpoch=epoch;
    try{
      let result;const starting=!started||key!==mediaKey;
      if(starting){
        narrator.cancel();snapshot=null;
        result=await send({kind:'ELT_START',source,position:v.currentTime});
      }else{
        const seek=seekPending&&!v.seeking;if(seek)seekPending=false;
        result=await send({kind:'ELT_CLOCK',sequence:++sequence,position:v.currentTime,paused:v.paused,rate:v.playbackRate,seek,
          narrating,narration_serial:narrationSerial});
      }
      if(currentEpoch!==epoch)return;
      if(result?.stopped){deactivate();return {stopped:true};}
      if(result?.error)throw Object.assign(Error(result.error),{code:result.error_code});
      if(!result?.session_id||!result.has_source)throw Object.assign(Error('本轮字幕会话未能建立，请重新开始。'),{code:'SESSION_EXPIRED'});
      if(starting){started=true;mediaKey=key;seekPending=false;}
      if(snapshot?.session_id===result.session_id&&(snapshot.playback?.playback_revision??0)>(result.playback?.playback_revision??0))result.playback=snapshot.playback;
      const speechRevision=result.playback?.speech_revision;
      if(Number.isInteger(speechRevision))result.cues=(result.cues||[]).map(c=>c.speech&&!c.speech.startsWith(speechRevision+'-')?{...c,speech:'',speech_seconds:0}:c);
      snapshot=result;narrator.setOptions?.(snapshot.playback);connectionError='';
      return {connected:true,status:result.status};
    }catch(error){
      if(currentEpoch===epoch){narrator.cancel();connectionError=error?.message||'网页连接不可用，请回到 ELT 主程序重新连接。';}
      return {error:error?.message||'网页连接不可用，请回到 ELT 主程序重新连接。',error_code:error?.code||'FOLLOW_FAILED'};
    }finally{if(currentEpoch===epoch)busy=false;}
  }
  function tick(){
    if(duckLease){const display=selectVideo();sourceVolume.tick(display&&ELTFollow.clockVideo(document.querySelectorAll('video'),display));}
    if(!owner||!host||!video)return;place();
    const clock={time:video.currentTime,rate:video.playbackRate,paused:video.paused,seeking:video.seeking};
    const cues=snapshot?.cues||[],cue=ELTFollow.activeCue(cues,clock.time);
    ELTFollow.renderCaption(host,original,translated,unlock,cue,snapshot?.playback);
    narrator.tick(cues,clock,snapshot?snapshot.session_id+':'+snapshot.generation:'loading');
  }
  function onPageHide(){if(owner)send({kind:'ELT_STOP'}).catch(()=>{});deactivate();}
  try{
    const extensionId=runtime.id;
    if(!extensionId){invalidate();return;}
    runtime.onMessage.addListener((message,sender,respond)=>{
      if(invalidated||sender.id!==extensionId)return;
      if(message.kind==='ELT_SOURCE_VOLUME'){
        if(!registeredDocument||message.document_id!==registeredDocument){respond({accepted:false});return;}
        if(message.active&&typeof message.lease==='string'&&/^[A-Za-z0-9-]{16,80}$/.test(message.lease)){
          duckLease=message.lease;sourceVolume.command(message);tick();
        }else if(message.lease===duckLease){sourceVolume.command({active:false});duckLease='';}
        respond({accepted:true});return;
      }
      if(message.kind==='ELT_PLAYBACK'){
        if(message.owner!==owner||!snapshot||message.session_id!==snapshot.session_id){respond({accepted:false});return;}
        if((message.playback?.playback_revision??0)>=(snapshot.playback?.playback_revision??0)){
          snapshot.playback=message.playback;
          snapshot.cues=(snapshot.cues||[]).map(c=>c.speech&&!c.speech.startsWith(message.playback.speech_revision+'-')?{...c,speech:'',speech_seconds:0}:c);
          narrator.setOptions(message.playback);tick();
        }
        respond({accepted:true});return;
      }
      if(message.kind==='ELT_ACTIVATE'){
        deactivate();owner=message.owner;show();register();
        heartbeat().then(result=>respond(result||{error:'网页播放器尚未准备好，请稍后再开始。',error_code:'PAGE_NOT_READY'}))
          .catch(()=>{}); // A closed popup/document may no longer accept its reply.
        return true;
      }
      if(message.kind==='ELT_DEACTIVATE'){
        if(message.owner&&message.owner!==owner){respond({stopped:false});return;}
        deactivate();respond({stopped:true});
      }
    });
  }catch{invalidate();return;}
  addEventListener('pagehide',onPageHide);
  timers.push(setInterval(register,3000),setInterval(heartbeat,250),setInterval(tick,50));
  register();
})();
