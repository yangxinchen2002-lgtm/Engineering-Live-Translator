importScripts('core.js');
const frames=new Map(), audioCache=new Map();let active=null,lastPing=0,pingBusy=false;
let volumeTarget=null,readingBusy=false,playbackOptions={},playbackSession='',lastNarrationSerial=-1;
const ERROR_TEXT={
  NOT_PAIRED:'尚未连接 ELT。请在 ELT.exe 中选择“网页视频预读”并启动，然后连接网页扩展。',
  SERVICE_OFFLINE:'无法连接 ELT 网页服务。请在 ELT.exe 中启动网页视频预读，再点击“连接网页跟随扩展”。',
  PAIR_EXPIRED:'配对已失效。请回到 ELT 网页连接页，重新点击“连接网页跟随扩展”。',
  SESSION_EXPIRED:'本轮字幕会话已停止，请在扩展中重新点击开始。',
  SERVICE_TIMEOUT:'ELT 网页服务响应超时，请检查 ELT 主程序，必要时重新启动网页跟随并连接。',
  START_REJECTED:'ELT 网页服务未能开始，请检查 ELT 主程序的错误提示。',
  PAGE_NOT_READY:'请刷新当前课程页，使用原网站播放按钮后再开始跟随。',
  FOLLOW_FAILED:'网页跟随连接失败，请回到 ELT 主程序检查连接。'
};
function problem(code,message){return Object.assign(Error(message||ERROR_TEXT[code]||ERROR_TEXT.FOLLOW_FAILED),{code});}
function replyError(error){const code=Object.hasOwn(ERROR_TEXT,error?.code)?error.code:'FOLLOW_FAILED';return {error:code===error?.code?error.message:ERROR_TEXT[code],error_code:code};}
async function localFetch(url,options){
  try{return await fetch(url,{...options,redirect:'error'});}
  catch(error){throw problem(['TimeoutError','AbortError'].includes(error?.name)?'SERVICE_TIMEOUT':'SERVICE_OFFLINE');}
}
async function checkedResponse(response){
  if(response.ok)return;
  if(response.status===403)throw problem('PAIR_EXPIRED');
  if(response.status===409)throw problem('SESSION_EXPIRED');
  let detail='';
  try{const body=await response.json();if(typeof body.error==='string'&&body.error.length<=180&&!/https?:\/\/|[A-Za-z0-9_-]{40,}/.test(body.error))detail=body.error;}catch{}
  throw problem('START_REJECTED',detail?'网页服务未能开始：'+detail:undefined);
}
async function pairing(){return (await chrome.storage.session.get('pairing')).pairing;}
async function request(path,data,asAudio=false){
  const p=await pairing();if(!p)throw problem('NOT_PAIRED');
  const response=await localFetch(p.origin+path,{method:data===undefined?'GET':'POST',credentials:'omit',
    headers:{'Content-Type':'application/json','X-ELT-Extension-Id':chrome.runtime.id,'X-ELT-Bridge-Token':p.token},
    ...(data===undefined?{}:{body:JSON.stringify(data)}),signal:AbortSignal.timeout(12000)});
  await checkedResponse(response);
  if(asAudio){
    if(Number(response.headers.get('content-length'))>2097152)throw Error('audio too large');
    const bytes=new Uint8Array(await response.arrayBuffer());if(bytes.length>2097152)throw Error('audio too large');
    let binary='';for(let at=0;at<bytes.length;at+=16384)binary+=String.fromCharCode(...bytes.subarray(at,at+16384));
    return btoa(binary);
  }
  return response.json();
}
function senderIsOwner(sender,message){
  return active&&message.owner===active.owner&&sender.tab?.id===active.tabId&&sender.frameId===active.frameId
    &&sender.documentId===active.documentId&&ELTFollow.pageAllowed(sender.url);
}
async function stopActive(){
  const old=active;active=null;audioCache.clear();
  releaseVolume();playbackOptions={};playbackSession='';lastNarrationSerial=-1;
  if(old){
    await chrome.tabs.sendMessage(old.tabId,{kind:'ELT_DEACTIVATE',owner:old.owner},{frameId:old.frameId}).catch(()=>{});
    await request('/bridge/stop',{owner:old.owner}).catch(()=>{});
  }
}
function volumeMessage(target,value){
  if(!target)return;
  chrome.tabs.sendMessage(target.tabId,{kind:'ELT_SOURCE_VOLUME',lease:target.owner,document_id:target.documentId,...value},
    {frameId:target.frameId}).catch(()=>{});
}
function releaseVolume(){const previous=volumeTarget;volumeTarget=null;volumeMessage(previous,{active:false});}
function routeVolume(playing,options,owner,serial){
  if(!active||active.owner!==owner||!Number.isSafeInteger(serial)||serial<lastNarrationSerial)return;
  lastNarrationSerial=serial;
  if(!playing||!options.narrate||!options.duck_source){releaseVolume();return;}
  const candidates=[...frames.values()].filter(f=>f.tabId===active.tabId&&Date.now()-f.seen<10000);
  const audible=candidates.filter(f=>f.audible),decoded=audible.filter(f=>f.audio_decoded);
  const target=decoded.length===1?decoded[0]:audible.length===1?audible[0]:
    candidates.find(f=>f.frameId===(volumeTarget?.frameId??active.frameId))||active;
  if(volumeTarget&&(volumeTarget.documentId!==target.documentId||volumeTarget.frameId!==target.frameId))releaseVolume();
  volumeTarget={...target,owner};volumeMessage(volumeTarget,{active:true,percent:options.source_percent});
}
function acceptPlayback(result,owner){
  if(!active||active.owner!==owner)return result;
  if(result.session_id!==playbackSession){playbackSession=result.session_id;playbackOptions={};}
  if((result.playback?.playback_revision??0)>=(playbackOptions.playback_revision??0))playbackOptions=result.playback||playbackOptions;
  else result.playback=playbackOptions;
  active.session_id=result.session_id;return result;
}
chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  (async()=>{
    if(!message||JSON.stringify(message).length>40000)throw Error('invalid message');
    if(message.kind==='ELT_PAIR'){
      const u=new URL(sender.url), requested=new URL(message.url);
      if(u.hostname!=='127.0.0.1'||u.protocol!=='http:'||u.origin!==requested.origin||!requested.hash)throw Error('invalid pairing page');
      await stopActive();
      const response=await localFetch(u.origin+'/bridge/pair',{method:'POST',credentials:'omit',signal:AbortSignal.timeout(5000),
        headers:{'Content-Type':'application/json','X-ELT-Lab-Token':requested.hash.slice(1),'X-ELT-Extension-Id':chrome.runtime.id},
        body:JSON.stringify({options:message.options})});
      await checkedResponse(response);const result=await response.json();
      await chrome.storage.session.set({pairing:{origin:u.origin,token:result.token,options:result.options}});
      if(result.options?.ui_language)await chrome.storage.local?.set({ui_language:result.options.ui_language});
      return {paired:true};
    }
    if(message.kind==='ELT_REGISTER'&&sender.tab&&ELTFollow.pageAllowed(sender.url)){
      if(!pingBusy&&Date.now()-lastPing>15000){
        pingBusy=true;lastPing=Date.now();
        request('/bridge/ping',{}).catch(()=>{}).finally(()=>{pingBusy=false;});
      }
      frames.set(sender.tab.id+':'+sender.frameId,{tabId:sender.tab.id,frameId:sender.frameId,documentId:sender.documentId,
        area:Math.max(0,Math.min(1e7,Number(message.area)||0)),audible:message.audible===true,
        audio_decoded:message.audio_decoded===true,seen:Date.now()});
      for(const [key,f] of frames)if(Date.now()-f.seen>60000)frames.delete(key);
      while(frames.size>64)frames.delete(frames.keys().next().value);
      return {active:senderIsOwner(sender,{owner:active?.owner}),document_id:sender.documentId};
    }
    // Popup commands are accepted only from this extension's own pages.
    if(['ELT_STATUS','ELT_ACTIVATE_TAB','ELT_STOP_TAB','ELT_GET_READING','ELT_SET_PLAYBACK'].includes(message.kind)){
      if(sender.id!==chrome.runtime.id||sender.tab||!sender.url?.startsWith(chrome.runtime.getURL('')))throw Error('invalid popup');
      if(message.kind==='ELT_STATUS'){
        const p=await pairing();if(!p)return {paired:false,ui_language:(await chrome.storage.local?.get('ui_language'))?.ui_language,...replyError(problem('NOT_PAIRED'))};
        try{const s=await request('/bridge/status');return {...s,origin:p.origin,activeTab:active?.tabId,language:p.options?.language,ui_language:p.options?.ui_language};}
        catch(error){return {paired:false,ui_language:p.options?.ui_language,...replyError(error)};}
      }
      if(message.kind==='ELT_STOP_TAB'){await stopActive();return {stopped:true};}
      if(message.kind==='ELT_GET_READING')return request('/bridge/settings');
      if(message.kind==='ELT_SET_PLAYBACK'){
        if(readingBusy)throw problem('FOLLOW_FAILED','设置正在应用，请稍后重试。');
        readingBusy=true;
        try{
          const owner=active?.owner||'',session_id=active?.session_id||'';
          const result=await request('/bridge/playback',{owner,session_id,options:message.options});
          if((active?.owner||'')!==owner)throw problem('SESSION_EXPIRED');
          if(owner){
            if(result.session_id!==active.session_id)throw problem('SESSION_EXPIRED');
            playbackOptions=result.playback;audioCache.clear();
            await chrome.tabs.sendMessage(active.tabId,{kind:'ELT_PLAYBACK',owner,session_id,playback:result.playback},{frameId:active.frameId}).catch(()=>{});
            if(!result.playback.narrate||!result.playback.duck_source)releaseVolume();
          }
          return result;
        }finally{readingBusy=false;}
      }
      const service=await request('/bridge/status');
      if(!service.paired)throw problem('PAIR_EXPIRED');
      const candidates=[...frames.values()].filter(f=>f.tabId===message.tabId&&Date.now()-f.seen<15000).sort((a,b)=>b.area-a.area);
      if(!candidates.length)throw problem('PAGE_NOT_READY');
      await stopActive();active={...candidates[0],owner:crypto.randomUUID(),language:message.language||'auto'};
      const activationOwner=active.owner;
      try{
        const result=await chrome.tabs.sendMessage(active.tabId,{kind:'ELT_ACTIVATE',owner:active.owner,language:active.language},{frameId:active.frameId});
        if(active?.owner!==activationOwner)throw problem('SESSION_EXPIRED');
        if(result?.stopped)throw problem('SESSION_EXPIRED');
        if(!result?.connected)throw problem(Object.hasOwn(ERROR_TEXT,result?.error_code)?result.error_code:'PAGE_NOT_READY',result?.error);
        return {active:true,status:result.status};
      }catch(error){if(active?.owner===activationOwner)await stopActive();throw error;}
    }
    if(!senderIsOwner(sender,message))throw problem('SESSION_EXPIRED');
    if(message.kind==='ELT_START'){
      if(!ELTFollow.mediaAllowed(message.source))throw Error('unsupported media');
      const owner=active.owner;return acceptPlayback(await request('/bridge/start',{...message,language:active.language}),owner);
    }
    if(message.kind==='ELT_CLOCK'){
      const owner=active.owner,result=acceptPlayback(await request('/bridge/clock',message),owner);
      routeVolume(message.narrating,result.playback||{},owner,message.narration_serial);return result;
    }
    if(message.kind==='ELT_DUCK'){routeVolume(message.playing,playbackOptions,active.owner,message.narration_serial);return {accepted:true};}
    if(message.kind==='ELT_AUDIO'){
      if(!/^[0-9-]+\.wav$/.test(message.name))throw Error('invalid audio');
      const key=active.owner+':'+message.name;
      if(!audioCache.has(key)){
        audioCache.set(key,await request('/bridge/audio/'+message.name+'?owner='+encodeURIComponent(active.owner),undefined,true));
        while(audioCache.size>3)audioCache.delete(audioCache.keys().next().value);
      }
      return {audio:audioCache.get(key)};
    }
    if(message.kind==='ELT_STOP'){await stopActive();return {stopped:true};}
    throw Error('unsupported message');
  })().then(respond,error=>respond(replyError(error)));
  return true;
});
chrome.tabs.onRemoved.addListener(id=>{for(const [key,f] of frames)if(f.tabId===id)frames.delete(key);if(active?.tabId===id)stopActive();});
