import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {randomUUID} from 'node:crypto';
import '../extension/core.js';
import '../extension/source-volume.js';
import '../extension/layout.js';
const source=name=>fs.readFileSync(new URL('../extension/'+name,import.meta.url),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const extension='a'.repeat(32),pageUrl='https://live.rbg.tum.de/w/1/2';
const popupSender={id:extension,url:'chrome-extension://'+extension+'/popup.html'};
const pageSender={tab:{id:42},frameId:0,documentId:'doc',url:pageUrl};
const ok=value=>({ok:true,status:200,json:async()=>value});

function background({paired=true,fetcher=async()=>ok({paired:true}),activate=async()=>({connected:true,status:'loading'})}={}){
  let listener,pair=paired?{origin:'http://127.0.0.1:1234',token:'test-only'}:null;
  const actions=[],deliveries=[];
  const context=vm.createContext({URL,AbortSignal,crypto:{randomUUID},importScripts(){},ELTFollow:globalThis.ELTFollow,
    fetch:fetcher,chrome:{runtime:{id:extension,getURL:p=>'chrome-extension://'+extension+'/'+p,onMessage:{addListener:fn=>listener=fn}},
      storage:{session:{get:async()=>({pairing:pair}),set:async data=>{pair=data.pairing;}}},
      tabs:{onRemoved:{addListener(){}},sendMessage:async(id,message,options)=>{
        actions.push(message.kind);deliveries.push({id,message,options});return message.kind==='ELT_ACTIVATE'?activate(message):{stopped:true};
      }}}});
  vm.runInContext(source('background.js'),context);
  const dispatch=(message,sender=popupSender)=>new Promise(resolve=>listener(message,sender,resolve));
  return {dispatch,actions,deliveries,register:()=>dispatch({kind:'ELT_REGISTER',area:100},pageSender)};
}

test('reading mutations are restricted to the extension popup',async()=>{
  let calls=0;const b=background({fetcher:async()=>{calls++;return ok({playback:{volume:30}});}});
  const result=await b.dispatch({kind:'ELT_SET_PLAYBACK',options:{volume:30}},pageSender);
  assert.ok(result.error);assert.equal(calls,0);
});

test('reading requests stay bounded when two popup contexts overlap',async()=>{
  let finish,calls=0;const b=background({fetcher:async()=>{calls++;return new Promise(resolve=>finish=resolve);}});
  const first=b.dispatch({kind:'ELT_SET_PLAYBACK',options:{volume:30}});await flush();
  const second=await b.dispatch({kind:'ELT_SET_PLAYBACK',options:{volume:40}});
  assert.ok(second.error);assert.equal(calls,1);
  finish(ok({playback:{volume:30},session_id:''}));assert.equal((await first).playback.volume,30);
});

test('manifest loads every real course script in the required order without extra permissions',async()=>{
  const manifest=JSON.parse(source('manifest.json'));assert.deepEqual(manifest.permissions,['storage']);
  const timers=[],messages=[];
  const context=vm.createContext({URL,Audio:class{addEventListener(){}},performance:{now:()=>0},
    chrome:{runtime:{id:extension,onMessage:{addListener(){}},sendMessage:async message=>{messages.push(message);return {document_id:'doc'};}}},
    document:{querySelectorAll:()=>[]},setInterval:(fn,ms)=>{timers.push(ms);return timers.length;},clearInterval(){},addEventListener(){},removeEventListener(){}});
  for(const file of manifest.content_scripts.find(entry=>entry.all_frames).js)vm.runInContext(source(file),context);
  await flush();assert.deepEqual(timers,[3000,250,50]);assert.equal(messages[0].kind,'ELT_REGISTER');
  for(const file of Object.values(manifest.icons))assert.ok(fs.readFileSync(new URL('../extension/'+file,import.meta.url)).length>32);
});

test('source volume targets the audible frame and old playback events cannot re-duck it',async()=>{
  let owner;const state={paired:true,session_id:'s',playback:{narrate:true,duck_source:true,source_percent:20,playback_revision:0}};
  const b=background({fetcher:async()=>ok(state),activate:message=>{owner=message.owner;return {connected:true};}});
  await b.register();await b.dispatch({kind:'ELT_REGISTER',area:50,audible:true,audio_decoded:true},
    {...pageSender,frameId:1,documentId:'sound-doc'});
  await b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42});await b.dispatch({kind:'ELT_START',owner,source:'https://edge.live.rbg.tum.de/a.mp4'},pageSender);
  await b.dispatch({kind:'ELT_DUCK',owner,playing:true,narration_serial:1},pageSender);
  let routed=b.deliveries.filter(d=>d.message.kind==='ELT_SOURCE_VOLUME');
  assert.equal(routed.at(-1).options.frameId,1);assert.equal(routed.at(-1).message.percent,20);
  await b.dispatch({kind:'ELT_DUCK',owner,playing:false,narration_serial:2},pageSender);
  await b.dispatch({kind:'ELT_CLOCK',owner,narrating:true,narration_serial:1},pageSender);
  routed=b.deliveries.filter(d=>d.message.kind==='ELT_SOURCE_VOLUME');assert.equal(routed.at(-1).message.active,false);
});

test('a delayed clock cannot overwrite newer popup settings',async()=>{
  let owner,finishClock;
  const b=background({fetcher:async url=>url.includes('/bridge/clock')?new Promise(resolve=>finishClock=resolve):
    ok({paired:true,session_id:'s',playback:{volume:url.includes('/bridge/playback')?30:80,playback_revision:url.includes('/bridge/playback')?2:0}}),
    activate:message=>{owner=message.owner;return {connected:true};}});
  await b.register();await b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42});
  await b.dispatch({kind:'ELT_START',owner,source:'https://edge.live.rbg.tum.de/a.mp4'},pageSender);
  const clock=b.dispatch({kind:'ELT_CLOCK',owner},pageSender);await flush();
  const settings=await b.dispatch({kind:'ELT_SET_PLAYBACK',options:{volume:30}});assert.equal(settings.playback.volume,30);
  finishClock(ok({session_id:'s',playback:{volume:80,playback_revision:0}}));
  assert.equal((await clock).playback.volume,30);
});

test('start without pairing is rejected before activating the page',async()=>{
  const b=background({paired:false});await b.register();
  const result=await b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42});
  assert.equal(result.error_code,'NOT_PAIRED');assert.match(result.error,/exe/);assert.deepEqual(b.actions,[]);
});
test('stored pairing cannot pretend that an offline local service has started',async()=>{
  const b=background({fetcher:async()=>{throw TypeError('Failed to fetch');}});await b.register();
  const result=await b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42});
  assert.equal(result.error_code,'SERVICE_OFFLINE');assert.equal(result.active,undefined);assert.deepEqual(b.actions,[]);
  assert.equal((await b.dispatch({kind:'ELT_STATUS'})).error_code,'SERVICE_OFFLINE');
});
test('expired pairing is distinguished from a stopped service',async()=>{
  const b=background({fetcher:async()=>({ok:false,status:403})});await b.register();
  assert.equal((await b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42})).error_code,'PAIR_EXPIRED');
  assert.deepEqual(b.actions,[]);
});
test('timeout is distinguished without activating a page',async()=>{
  const b=background({fetcher:async()=>{throw Object.assign(Error('timeout'),{name:'TimeoutError'});}});await b.register();
  assert.equal((await b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42})).error_code,'SERVICE_TIMEOUT');
  assert.deepEqual(b.actions,[]);
});
test('failed initial capture rolls back activation instead of returning success',async()=>{
  const b=background({activate:async()=>({error:'start rejected',error_code:'START_REJECTED'})});await b.register();
  const r=await b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42});
  assert.equal(r.error_code,'START_REJECTED');assert.equal(r.active,undefined);
  assert.deepEqual(b.actions,['ELT_ACTIVATE','ELT_DEACTIVATE']);
});
test('start waits for the actual source acknowledgement and reports loading truthfully',async()=>{
  let acknowledge,finished=false;
  const b=background({activate:()=>new Promise(resolve=>{acknowledge=resolve;})});await b.register();
  const pending=b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42}).then(r=>{finished=true;return r;});
  await flush();assert.equal(finished,false);
  acknowledge({connected:true,status:'loading'});
  const result=await pending;assert.equal(result.active,true);assert.equal(result.status,'loading');
});
test('server rejection keeps useful diagnostics but does not expose media URLs',async()=>{
  for(const detail of ['请先停止正式 ELT 的字幕和朗读','https://video.opencast.tum.de/a.mp4?secret=test']){
    const b=background({fetcher:async()=>({ok:false,status:400,json:async()=>({error:detail})})});await b.register();
    const result=await b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42});
    assert.equal(result.error_code,'START_REJECTED');assert.doesNotMatch(result.error,/https:\/\/|secret=/);
    if(!detail.startsWith('https:'))assert.match(result.error,/停止正式 ELT/);
  }
});
test('a late failed start cannot tear down a newer source session',async()=>{
  let rejectOld,count=0,newOwner;
  const b=background({activate:message=>{
    if(++count===1)return new Promise((_,reject)=>{rejectOld=reject;});
    newOwner=message.owner;return Promise.resolve({connected:true,status:'loading'});
  }});await b.register();
  const old=b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42});await flush();
  assert.equal((await b.dispatch({kind:'ELT_ACTIVATE_TAB',tabId:42})).active,true);
  rejectOld(Error('old page closed'));assert.ok((await old).error);
  assert.equal(b.actions.filter(x=>x==='ELT_DEACTIVATE').length,1);
  assert.equal((await b.dispatch({kind:'ELT_CLOCK',owner:newOwner},pageSender)).error,undefined);
});

class Element{
  constructor(tag='div'){this.tag=tag;this.style={};this.textContent='';this.children=[];this.listeners=new Map();}
  append(...items){for(const item of items){item.parentElement=this;this.children.push(item);}}
  attachShadow(){return this.shadow=new Element('shadow');}
  addEventListener(name,fn){this.listeners.set(name,fn);}
  removeEventListener(name){this.listeners.delete(name);}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(c=>c!==this);}
  set innerHTML(value){
    this.html=value;this.children=[];
    for(const [id,tag,cls] of [['o','p','elt-source'],['t','p','elt-translation'],['elt-close','button',''],['elt-unlock','button','']]){
      const node=new Element(tag);node.id=id;node.className=cls;node.hidden=id==='elt-unlock';this.append(node);
    }
  }
  querySelector(selector){return this.children.find(e=>selector.startsWith('#')?e.id===selector.slice(1):e.tag===selector);}
  getBoundingClientRect(){return {width:640};}
  get scrollHeight(){return 22;}
}
function content(){
  let listener,serial=0;const timers=new Map(),messages=[],applied=[],ticks=[];
  const body=new Element(),created=[],video=new Element('video');
  Object.assign(video,{duration:120,currentTime:20,paused:false,playbackRate:1,seeking:false,volume:1,muted:false,
    getBoundingClientRect:()=>({width:640,height:360,left:0,bottom:360})});
  let clockFails=false,clockStops=false,attempts=0;
  const state={session_id:'session',has_source:true,status:'loading',generation:1,prepared_until:30,metrics:{},
    playback:{volume:80,speech_revision:0,playback_revision:0},
    cues:[{id:'a',start:10,end:30,source:'recognized original',translation:''}]};
  const runtime={id:extension,onMessage:{addListener:fn=>listener=fn},sendMessage:async message=>{
    messages.push(message.kind);
    if(message.kind==='ELT_START'&&++attempts===1)return {error:'service offline',error_code:'SERVICE_OFFLINE'};
    if(message.kind==='ELT_CLOCK'&&clockStops)return {stopped:true};
    if(message.kind==='ELT_CLOCK'&&clockFails)return {error:'temporary service timeout',error_code:'SERVICE_TIMEOUT'};
    return message.kind==='ELT_REGISTER'?{document_id:'doc'}:structuredClone(state);
  }};
  const context=vm.createContext({chrome:{runtime},URL,innerWidth:1280,innerHeight:720,Audio:class{addEventListener(){}},
    document:{body,querySelectorAll:()=>[video],createElement:tag=>{const e=new Element(tag);created.push(e);return e;}},
    performance:{getEntriesByType:()=>[]},
    ELTFollow:{...globalThis.ELTFollow,captionCSS:'',fitCaption(){},
      discover:()=> 'https://edge.live.rbg.tum.de/a.m3u8',Narrator:class{cancel(){}setOptions(v){applied.push(v);}tick(cues){ticks.push(cues);}}},
    setInterval:(fn,ms)=>{timers.set(++serial,{fn,ms});return serial;},clearInterval:id=>timers.delete(id),
    addEventListener(){},removeEventListener(){}});
  vm.runInContext(source('runtime.js'),context);vm.runInContext(source('content.js'),context);
  return {messages,created,video,state,applied,ticks,command:message=>new Promise(resolve=>listener(message,{id:extension},resolve)),
    failClock:()=>{clockFails=true;},stopClock:()=>{clockStops=true;},
    timer:ms=>[...timers.values()].find(t=>t.ms===ms).fn,
    deactivate:owner=>new Promise(resolve=>listener({kind:'ELT_DEACTIVATE',owner},{id:extension},resolve)),
    activate:()=>new Promise(resolve=>listener({kind:'ELT_ACTIVATE',owner:'test-owner'},{id:extension},resolve))};
}

test('an inactive sound frame accepts only commands for its current document and restores the matching lease',async()=>{
  const c=content();await flush();const lease='volume-'+'a'.repeat(20);
  assert.equal((await c.command({kind:'ELT_SOURCE_VOLUME',lease,document_id:'stale',active:true,percent:20})).accepted,false);
  assert.equal(c.video.volume,1);
  await c.command({kind:'ELT_SOURCE_VOLUME',lease,document_id:'doc',active:true,percent:20});assert.equal(c.video.volume,.2);
  await c.command({kind:'ELT_SOURCE_VOLUME',lease:'older',document_id:'doc',active:false});assert.equal(c.video.volume,.2);
  await c.command({kind:'ELT_SOURCE_VOLUME',lease,document_id:'doc',active:false});assert.equal(c.video.volume,1);
  assert.equal(c.video.currentTime,20);assert.equal(c.video.paused,false);
});

test('an older heartbeat cannot undo a live popup change or reintroduce the old voice file',async()=>{
  const c=content();await c.activate();await c.timer(250)();
  const playback={volume:30,speech_revision:1,playback_revision:2};
  assert.equal((await c.command({kind:'ELT_PLAYBACK',owner:'test-owner',session_id:'session',playback})).accepted,true);
  c.state.cues[0].speech='0-old.wav';await c.timer(250)();c.timer(50)();
  assert.equal(c.applied.at(-1).volume,30);assert.equal(c.applied.at(-1).speech_revision,1);assert.equal(c.ticks.at(-1)[0].speech,'');
});
test('initial failure retries START, not a clock for a nonexistent session',async()=>{
  const c=content();const first=await c.activate();assert.equal(first.error_code,'SERVICE_OFFLINE');
  const second=await c.timer(250)();assert.equal(second.connected,true);
  await c.timer(250)();
  assert.deepEqual(c.messages.filter(x=>x==='ELT_START'||x==='ELT_CLOCK'),['ELT_START','ELT_START','ELT_CLOCK']);
});
test('temporary local connection failure preserves already prepared source text',async()=>{
  const c=content();await c.activate();await c.timer(250)();c.timer(50)();
  const root=c.created.find(e=>e.id==='elt-follow-overlay').shadow;
  const original=root.querySelector('#o');assert.equal(original.textContent,'recognized original');
  c.failClock();await c.timer(250)();c.timer(50)();
  assert.equal(original.textContent,'recognized original');
  assert.equal(root.querySelector('small'),undefined);assert.equal(c.video.paused,false);
});
test('a stale stop message cannot stop the current content session',async()=>{
  const c=content();await c.activate();await c.timer(250)();
  assert.equal((await c.deactivate('old-owner')).stopped,false);
  assert.equal((await c.timer(250)()).connected,true);
  assert.equal((await c.deactivate('test-owner')).stopped,true);
  const count=c.messages.length;await c.timer(250)();assert.equal(c.messages.length,count);
});
test('a desktop STOP response removes the page session without an error loop',async()=>{
  const c=content();await c.activate();await c.timer(250)();c.stopClock();
  assert.equal((await c.timer(250)()).stopped,true);
  const count=c.messages.length;await c.timer(250)();assert.equal(c.messages.length,count);
});
test('popup never labels a failed activation as started',async()=>{
  const elements=Object.fromEntries(['status','start','stop','language','dot','message','reading','narrate','model','voice','speed','volume','volumeValue','duck','source','captions','captionWidth','captionHeight','captionFont'].map(id=>[id,{textContent:'',value:'en',disabled:false}]));
  const context=vm.createContext({document:{getElementById:id=>elements[id]},chrome:{
    tabs:{query:async()=>[{id:42}]},runtime:{sendMessage:async message=>message.kind==='ELT_STATUS'?{paired:false,error:'service offline'}:
      {error:'请打开实验 EXE 后重新连接',error_code:'SERVICE_OFFLINE'}}}});
  vm.runInContext(source('popup.js'),context);await flush();await elements.start.onclick();
  assert.match(elements.status.textContent,/重新连接/);assert.doesNotMatch(elements.status.textContent,/已开始|已连接/);
  assert.equal(elements.start.disabled,false);
});
