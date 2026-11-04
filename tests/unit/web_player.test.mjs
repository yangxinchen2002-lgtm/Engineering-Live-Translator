import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import '../../app/web_follow/extension/core.js';
import '../../app/web_follow/extension/source-volume.js';
import '../../app/web_follow/extension/layout.js';
const script=fs.readFileSync(new URL('../../app/web_follow/web/player-observer.js',import.meta.url),'utf8').replace('__ELT_NONCE__','"test-only"');

function fixture({local=false,untrusted=false}={}){
  const sent=[],timers=[],ticks=[],nodes=new Map(),audios=[],narrators=[];let cancelled=0;
  const hosts=[],body={appendChild(node){node.parentNode=this;}},node=()=>({style:{},textContent:'',hidden:true,scrollHeight:22,getBoundingClientRect:()=>({width:900})});
  const video={duration:30,currentTime:3,paused:false,seeking:false,playbackRate:1,volume:1,muted:false,
    getBoundingClientRect:()=>({left:0,right:1000,bottom:600,width:1000,height:600}),addEventListener(){},
    pause(){throw Error('Original video must not be paused');},play(){throw Error('Original video must not be played');}};
  for(const name of ['currentTime','playbackRate','paused']){
    const value=video[name];Object.defineProperty(video,name,{get:()=>value,set:()=>{throw Error('Original clock must be read only');}});
  }
  const document={body,fullscreenElement:null,querySelectorAll:()=>[video],createElement:()=>{const host={style:{},remove(){this.parentNode=null;},
    attachShadow(){return {addEventListener(){},set innerHTML(value){},querySelector(id){if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);}};}};hosts.push(host);return host;}};
  const context={console,document,location:{href:'https://live.rbg.tum.de/w/example'},crypto:{randomUUID:()=>('a'.repeat(36))},
    chrome:{webview:{postMessage:value=>sent.push(value)}},performance:{getEntriesByType:()=>[],now:()=>0},
    innerWidth:1000,innerHeight:650,addEventListener(){},setInterval:fn=>timers.push(fn),setTimeout,clearTimeout,atob,Uint8Array,Blob,URL,
    Audio:class{constructor(){this.events=new Map();audios.push(this);}addEventListener(name,fn){this.events.set(name,fn);}play(){return Promise.resolve();}},ELTFollow:{pageAllowed:()=>true,discover:()=> 'https://edge.live.rbg.tum.de/a.mp4',
      SourceVolume:globalThis.ELTFollow.SourceVolume,
      captionCSS:globalThis.ELTFollow.captionCSS,captionMarkup:globalThis.ELTFollow.captionMarkup,
      placeCaption:globalThis.ELTFollow.placeCaption,renderCaption:globalThis.ELTFollow.renderCaption,
      fitCaption(){},activeCue:cues=>cues[0],Narrator:class{constructor(audio,load){this.load=load;narrators.push(this);}cancel(){cancelled++;}
        setOptions(value){this.options=value;}tick(cues,clock,session){ticks.push({cues,clock,session});}}}};
  if(local){context.__eltLocalPlayerOrigin='http://127.0.0.1:1234';context.location={origin:context.__eltLocalPlayerOrigin,href:context.__eltLocalPlayerOrigin+'/p/test/player.html'};video.currentSrc=context.__eltLocalPlayerOrigin+'/m/test';}
  if(untrusted){context.location={origin:'http://127.0.0.1:9999',href:'http://127.0.0.1:9999/unrelated'};context.ELTFollow.pageAllowed=()=>false;}
  context.window=context;vm.runInNewContext(script,context);
  return {context,video,sent,timers,ticks,nodes,hosts,audios,narrators,cancelled:()=>cancelled};
}

test('native captions hide the empty panel, apply live size and close only subtitles',()=>{
  const f=fixture();f.context.__eltPlayer.update({session_id:'s',generation:1,cues:[]});f.timers[0]();
  assert.equal(f.hosts[0].hidden,true);
  f.context.__eltPlayer.update({session_id:'s',generation:1,cues:[{source:'原文',translation:'中文'}],
    playback:{caption_width:60,caption_height:96,caption_font_size:14}});f.timers[0]();
  assert.equal(f.hosts[0].hidden,false);assert.equal(f.hosts[0].style.width,'600px');assert.equal(f.hosts[0].style.maxHeight,'96px');
  assert.equal(f.nodes.get('#t').style.fontSize,'14px');
  assert.ok(!globalThis.ELTFollow.captionMarkup.includes('small'));
  f.nodes.get('#elt-close').onclick();assert.equal(f.sent.at(-1).kind,'stop');assert.equal(f.video.paused,false);
});

test('owned local page reports its capability URL and uses the same subtitle clock',()=>{
  const f=fixture({local:true});f.timers[0]();assert.equal(f.sent[0].source,'http://127.0.0.1:1234/m/test');
  assert.equal(f.sent[0].position,3);f.context.__eltPlayer.mediaError(4);
  assert.equal(f.sent.at(-1).kind,'media_error');assert.equal(f.video.paused,false);
});

test('an unrelated localhost page cannot install the native observer',()=>{
  const f=fixture({untrusted:true});assert.equal(f.context.__eltPlayer,undefined);assert.equal(f.timers.length,0);
});

test('native audio bridge resolves returned bytes and reports an unavailable file explicitly',async()=>{
  const f=fixture(),reading=f.narrators[0].load({speech:'0-1-0-1000.wav'});
  const request=f.sent.at(-1);assert.equal(request.kind,'audio');assert.equal(request.name,'0-1-0-1000.wav');
  f.context.__eltPlayer.audio(request.id,Buffer.from('RIFFtest').toString('base64'));
  const url=await reading;
  try{assert.equal(await (await fetch(url)).text(),'RIFFtest');}finally{URL.revokeObjectURL(url);}
  const missing=f.narrators[0].load({speech:'0-1-1000-2000.wav'});
  f.context.__eltPlayer.audio(f.sent.at(-1).id,'');await assert.rejects(missing,/audio unavailable/);
});

test('native playback diagnostics distinguish playing and ended from generating audio',()=>{
  const f=fixture();f.audios[0].events.get('playing')();f.audios[0].events.get('ended')();
  assert.deepEqual(f.sent.map(x=>[x.kind,x.event]),[['playback','playing'],['playback','ended']]);
  assert.equal(f.video.paused,false);
});

test('quick toolbar options survive the next observer tick without touching the video',()=>{
  const f=fixture();f.context.__eltPlayer.update({session_id:'s',generation:1,cues:[],playback:{narrate:true}});
  const options={narrate:false,base_speed:1.4,volume:40,speech_revision:2};
  f.context.__eltPlayer.setPlayback(options);f.timers[0]();
  assert.equal(f.narrators[0].options,options);assert.equal(f.video.currentTime,3);assert.equal(f.video.paused,false);
});

test('native adapter sends real media clock and renders source and translation without writing to video',()=>{
  const f=fixture();f.timers[0]();assert.equal(f.sent[0].position,3);assert.equal(f.sent[0].paused,false);
  f.context.__eltPlayer.update({session_id:'session',generation:2,cues:[{source:'A complete sentence.',translation:'完整的一句话。'}]});
  f.timers[0]();assert.equal(f.nodes.get('#o').textContent,'A complete sentence.');
  assert.equal(f.nodes.get('#t').textContent,'完整的一句话。');assert.equal(f.ticks[0].clock.time,3);
  assert.equal(f.ticks[0].session,'session:2');
});

test('stopping native subtitles cancels narration and leaves the source clock untouched',()=>{
  const f=fixture();f.context.__eltPlayer.update({session_id:'s',generation:1,cues:[]});
  f.context.__eltPlayer.stop();f.timers[0]();assert.equal(f.cancelled(),1);assert.equal(f.ticks.length,0);
  assert.equal(f.video.currentTime,3);assert.equal(f.video.paused,false);
});

test('native duck command changes only soundtrack volume and stop restores it',()=>{
  const f=fixture();f.video.volume=.6;
  f.context.__eltPlayer.setSourceVolume({active:true,percent:20});
  assert.ok(Math.abs(f.video.volume-.12)<1e-10);
  f.timers[0]();assert.ok(Math.abs(f.video.volume-.12)<1e-10);
  f.context.__eltPlayer.setSourceVolume({active:true,percent:50});assert.equal(f.video.volume,.3);
  f.context.__eltPlayer.stop();assert.equal(f.video.volume,.6);
  assert.equal(f.video.currentTime,3);assert.equal(f.video.paused,false);assert.equal(f.video.muted,false);
});

test('dual-video source ducking chooses the audible soundtrack instead of muted slides',()=>{
  const f=fixture();f.video.muted=true;f.video.volume=.8;
  const master={duration:30,currentTime:5.5,paused:false,seeking:false,playbackRate:1,muted:false,volume:.7,addEventListener(){}};
  f.context.document.querySelectorAll=()=>[f.video,master];f.context.ELTFollow.clockVideo=globalThis.ELTFollow.clockVideo;
  f.context.__eltPlayer.setSourceVolume({active:true,percent:20});
  assert.ok(Math.abs(master.volume-.14)<1e-10);assert.equal(f.video.volume,.8);
  f.context.__eltPlayer.setSourceVolume({active:false});assert.equal(master.volume,.7);
});

test('muted slides can be 2.5 seconds behind without delaying the soundtrack clock',()=>{
  const slides={duration:30,currentTime:3,muted:true,volume:1},camera={duration:30,currentTime:5.5,muted:false,volume:1};
  const follow=globalThis.ELTFollow;
  assert.equal(follow.clockVideo([slides,camera],slides),camera);
  camera.muted=true;assert.equal(follow.clockVideo([slides,camera],slides),camera);
  camera.muted=false;assert.equal(slides.currentTime,3);
});

test('native cross-frame captions use the main audio clock rather than the secondary picture',()=>{
  const f=fixture();f.context.__eltPlayer.update({session_id:'s',generation:1,cues:[],
    player_clock:{cross_frame:true,position:5.5,rate:1,paused:false}});
  f.timers[0]();assert.equal(f.ticks[0].clock.time,5.5);assert.equal(f.video.currentTime,3);
});

test('native same-document dual video observes the soundtrack time and keeps the large-picture overlay',()=>{
  const f=fixture();f.video.muted=true;f.video.volume=1;f.video.clientWidth=1000;f.video.clientHeight=600;
  const master={duration:30,currentTime:5.5,paused:false,seeking:false,playbackRate:1,muted:false,volume:1,
    clientWidth:200,clientHeight:120,addEventListener(){}};
  f.context.document.querySelectorAll=()=>[f.video,master];f.context.ELTFollow.clockVideo=globalThis.ELTFollow.clockVideo;
  f.context.__eltPlayer.update({session_id:'s',generation:1,cues:[]});f.timers[0]();
  assert.equal(f.sent[0].position,5.5);assert.equal(f.sent[0].area,600000);assert.equal(f.ticks[0].clock.time,5.5);
  assert.equal(f.video.currentTime,3);
});

test('media discovery prefers the selected player source to a different resource playlist',()=>{
  const video={currentSrc:'blob:owned-video',closest:()=>({player:{currentSource:()=>({src:'https://edge.live.rbg.tum.de/primary.m3u8'})}})};
  assert.equal(globalThis.ELTFollow.discover(video,['https://edge.live.rbg.tum.de/other.m3u8']),
    'https://edge.live.rbg.tum.de/primary.m3u8');
});
