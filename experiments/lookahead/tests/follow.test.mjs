import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import '../extension/core.js';
const {fitRate,discover,mediaAllowed,Narrator}=globalThis.ELTFollow;
class Audio extends EventTarget{
  constructor(){super();this.paused=true;this.ended=false;this.duration=6;this.currentTime=0;this.playbackRate=1;this.plays=0;}
  pause(){this.paused=true;}
  play(){this.plays++;this.paused=false;return Promise.resolve();}
  load(){}
  removeAttribute(){}
  set src(value){this._src=value;this.currentTime=0;this.ended=false;}
  get src(){return this._src;}
}
const cue={id:'a',start:10,end:14,speech:'1-10000-0.wav',speech_seconds:6};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('fit speech to the source sentence and video speed',()=>{
  assert.equal(fitRate(6,4,1).rate,1.5);
  assert.equal(fitRate(6,4,2).rate,3);
  assert.equal(fitRate(1,10,1).rate,1);
  assert.equal(fitRate(2,10,2).rate,1);
  assert.equal(fitRate(6,4,.5).rate,1);
  assert.equal(fitRate(20,1,1).rate,4);
  assert.equal(fitRate(20,1,1).fits,false);
});
test('automatic discovery accepts only authorized media hosts',()=>{
  assert.equal(discover({currentSrc:'https://video.opencast.tum.de/a.mp4'},[]),'https://video.opencast.tum.de/a.mp4');
  assert.equal(discover({currentSrc:'blob:https://live.rbg.tum.de/x'},[{name:'https://edge.live.rbg.tum.de/a.m3u8?jwt=test-only'}]),'https://edge.live.rbg.tum.de/a.m3u8?jwt=test-only');
  assert.equal(mediaAllowed('https://evil.example/a.mp4'),false);
  assert.equal(mediaAllowed('https://user:pass@edge.live.rbg.tum.de/a.m3u8'),false);
});
test('speech adjusts, pauses with user and is ended at the source deadline',async()=>{
  const audio=new Audio(),events=[];const n=new Narrator(audio,async()=>'/test.wav',e=>events.push(e));
  n.tick([cue],{time:10,rate:1,paused:false},'s');await flush();
  assert.equal(audio.playbackRate,1.5);assert.equal(audio.paused,false);
  audio.currentTime=1.5;
  n.tick([cue],{time:11,rate:1,paused:true},'s');assert.equal(audio.paused,true);
  n.tick([cue],{time:11,rate:2,paused:false},'s');assert.equal(audio.playbackRate,3);
  n.tick([cue],{time:13,rate:1,paused:false},'s');
  n.tick([cue],{time:14,rate:1,paused:false},'s');assert.equal(audio.paused,true);assert.ok(events.includes('deadline'));
});
test('late files never start an expired narration',async()=>{
  let done;const audio=new Audio(),n=new Narrator(audio,()=>new Promise(r=>done=r));
  n.tick([cue],{time:10,rate:1,paused:false},'s');
  n.tick([cue],{time:14,rate:1,paused:false},'s');done('/late.wav');await flush();
  assert.equal(audio.plays,0);
});
test('one sentence keeps its cadence despite audio and browser clock jitter',async()=>{
  const audio=new Audio(),n=new Narrator(audio,async()=>'/sentence.wav');
  n.tick([cue],{time:10,rate:1,paused:false},'s');await flush();
  assert.equal(audio.playbackRate,1.5);
  for(const [time,played] of [[10.8,.4],[11.7,2.9],[13.2,5.7]]){
    audio.currentTime=played;n.tick([cue],{time,rate:1,paused:false},'s');assert.equal(audio.playbackRate,1.5);
  }
  n.tick([cue],{time:13.3,rate:.75,paused:false},'s');assert.equal(audio.playbackRate,1);
});
test('normal-speed narration finishes early and waits without replaying or starting the next cue',async()=>{
  const audio=new Audio();audio.duration=1;
  const short={...cue,speech_seconds:1},next={...short,id:'b',start:14,end:18};
  const n=new Narrator(audio,async()=>'/short.wav');
  n.tick([short,next],{time:10,rate:1,paused:false},'s');await flush();
  assert.equal(audio.playbackRate,1);assert.equal(audio.plays,1);
  audio.currentTime=1;audio.ended=true;audio.paused=true;audio.dispatchEvent(new Event('ended'));
  n.tick([short,next],{time:11,rate:1,paused:false},'s');await flush();
  n.tick([short,next],{time:13.9,rate:1,paused:false},'s');await flush();
  assert.equal(audio.plays,1);assert.equal(n.current,null);
  n.tick([short,next],{time:14,rate:1,paused:false},'s');await flush();
  assert.equal(audio.plays,2);assert.equal(audio.playbackRate,1);
});
test('faster video does not speed up a translation that still fits at normal speed',async()=>{
  const audio=new Audio();audio.duration=2;
  const short={...cue,end:18,speech_seconds:2},n=new Narrator(audio,async()=>'/short.wav');
  n.tick([short],{time:10,rate:1,paused:false},'s');await flush();
  audio.currentTime=1;
  n.tick([short],{time:11,rate:2,paused:false},'s');assert.equal(audio.playbackRate,1);
  n.tick([short],{time:11.2,rate:.5,paused:false},'s');assert.equal(audio.playbackRate,1);
});
test('a changed video speed accelerates only as much as the remaining sentence needs',async()=>{
  const audio=new Audio();audio.duration=4;
  const sentence={...cue,speech_seconds:4},n=new Narrator(audio,async()=>'/sentence.wav');
  n.tick([sentence],{time:10,rate:1,paused:false},'s');await flush();assert.equal(audio.playbackRate,1);
  audio.currentTime=1;
  n.tick([sentence],{time:11,rate:2,paused:false},'s');assert.equal(audio.playbackRate,2);
  audio.currentTime=3;
  n.tick([sentence],{time:12,rate:2,paused:false},'s');assert.equal(audio.playbackRate,2);
});
test('formal desktop base speed and volume are respected without slowing below the chosen base',async()=>{
  const audio=new Audio();audio.duration=1;
  const short={...cue,speech_seconds:1},n=new Narrator(audio,async()=>'/short.wav');
  n.setOptions({base_speed:1.25,volume:30});
  n.tick([short],{time:10,rate:1,paused:false},'s');await flush();
  assert.equal(audio.playbackRate,1.25);assert.equal(audio.volume,.3);
  n.setOptions({base_speed:.8,volume:200});
  n.tick([short],{time:11,rate:1,paused:false},'s');assert.equal(audio.playbackRate,1.25);
});
test('future sentence audio is loaded once before its time and cannot autoplay early',async()=>{
  const audio=new Audio(),loads=[],n=new Narrator(audio,async c=>{loads.push(c.id);return '/future.wav';});
  n.tick([cue],{time:8,rate:1,paused:false},'s');await flush();
  assert.deepEqual(loads,['a']);assert.equal(audio.plays,0);
  n.tick([cue],{time:9,rate:1,paused:false},'s');await flush();assert.deepEqual(loads,['a']);
  n.tick([cue],{time:10,rate:1,paused:false},'s');await flush();
  assert.deepEqual(loads,['a']);assert.equal(audio.plays,1);assert.equal(audio.playbackRate,1.5);
});

test('quick narration toggle stops only its audio and prevents disabled prefetch',async()=>{
  const audio=new Audio(),loads=[],n=new Narrator(audio,async c=>{loads.push(c.id);return '/speech.wav';});
  n.tick([cue],{time:10,rate:1,paused:false},'s');await flush();assert.equal(audio.plays,1);
  n.setOptions({narrate:false});assert.equal(audio.paused,true);
  const next={...cue,id:'next',start:14,end:18};
  n.tick([cue,next],{time:12,rate:1,paused:false},'s');await flush();
  assert.deepEqual(loads,['a']);assert.equal(n.current,null);
  n.setOptions({narrate:true});n.tick([next],{time:14,rate:1,paused:false},'s');await flush();
  assert.equal(audio.plays,2);assert.deepEqual(loads,['a','next']);
});

test('changing voice revision rejects old pending audio even when cue identity is unchanged',async()=>{
  let done;const audio=new Audio(),n=new Narrator(audio,()=>new Promise(r=>done=r));
  n.tick([cue],{time:10,rate:1,paused:false},'s');
  n.setOptions({speech_revision:1});done('/old-voice.wav');await flush();
  assert.equal(audio.plays,0);assert.equal(n.current,null);assert.equal(n.speechRevision,1);
  n.load=async()=>'/new-voice.wav';n.tick([cue],{time:11,rate:1,paused:false},'s');await flush();
  assert.equal(audio.plays,1);assert.equal(audio.src,'/new-voice.wav');
});

test('base speed and volume update current speech without loading the sentence again',async()=>{
  const audio=new Audio();audio.duration=1;
  let loads=0;const short={...cue,speech_seconds:1},n=new Narrator(audio,async()=>{loads++;return '/short.wav';});
  n.tick([short],{time:10,rate:1,paused:false},'s');await flush();assert.equal(audio.playbackRate,1);
  n.setOptions({base_speed:1.3,volume:65});
  n.tick([short],{time:10.2,rate:1,paused:false},'s');
  assert.equal(loads,1);assert.equal(audio.playbackRate,1.3);assert.equal(audio.volume,.65);
});
test('reset cancels a pending future audio fetch',async()=>{
  let done;const audio=new Audio(),n=new Narrator(audio,()=>new Promise(r=>done=r));
  n.tick([cue],{time:8,rate:1,paused:false},'s');await flush();
  n.tick([],{time:30,rate:1,paused:false,seeking:true},'new');done('/stale.wav');await flush();
  assert.equal(audio.plays,0);assert.equal(n.preloaded,null);
});
test('seek and source change invalidate in-flight speech',async()=>{
  let done;const audio=new Audio(),n=new Narrator(audio,()=>new Promise(r=>done=r));
  n.tick([cue],{time:10,rate:1,paused:false},'s');
  n.tick([],{time:30,rate:1,paused:false,seeking:true},'new');done('/old.wav');await flush();
  assert.equal(audio.plays,0);assert.equal(n.current,null);
});
test('autoplay refusal is explicit and does not hammer play',async()=>{
  const audio=new Audio(),events=[];audio.play=()=>{audio.plays++;return Promise.reject(Object.assign(Error(),{name:'NotAllowedError'}));};
  const n=new Narrator(audio,async()=>'/test.wav',e=>events.push(e));
  n.tick([cue],{time:10,rate:1,paused:false},'s');await flush();
  n.tick([cue],{time:10.1,rate:1,paused:false},'s');await flush();
  assert.equal(audio.plays,1);assert.ok(events.includes('permission'));
});
test('original-page adapter contains no video control writes',()=>{
  const code=fs.readFileSync(new URL('../extension/content.js',import.meta.url),'utf8');
  assert.doesNotMatch(code,/\b(?:video|v)\.(?:pause|play|load)\s*\(/);
  assert.doesNotMatch(code,/\b(?:video|v)\.(?:currentTime|playbackRate|muted|volume)\s*=/);
  const local=fs.readFileSync(new URL('../web/app.js',import.meta.url),'utf8');
  const writes=local.split('\n').filter(line=>/video\.pause\(/.test(line));
  assert.equal(writes.length,1);assert.match(writes[0],/\$\('pause'\)\.onclick/);
});
