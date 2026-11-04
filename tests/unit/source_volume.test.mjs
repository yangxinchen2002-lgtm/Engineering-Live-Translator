import test from 'node:test';
import assert from 'node:assert/strict';
import '../../app/web_follow/extension/core.js';
import '../../app/web_follow/extension/source-volume.js';
const {SourceVolume}=globalThis.ELTFollow;
class Video extends EventTarget {
  constructor(volume=.6){super();this._volume=volume;this.paused=false;this.muted=false;this.currentTime=4;this.playbackRate=1;}
  get volume(){return this._volume;}
  set volume(value){this._volume=value;this.dispatchEvent(new Event('volumechange'));}
  play(){throw Error('Video playback is user controlled');}
  pause(){throw Error('Video playback is user controlled');}
}
const near=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-10,`${actual} != ${expected}`);
test('source volume uses a stable relative baseline and restores it after speech',()=>{
  const v=new Video(),duck=new SourceVolume(()=>0);
  duck.command({active:true,percent:20});duck.tick(v);near(v.volume,.12);
  for(let i=0;i<50;i++)duck.tick(v);near(v.volume,.12);
  duck.command({active:true,percent:50});duck.tick(v);near(v.volume,.3);
  duck.command({active:false});near(v.volume,.6);
  assert.equal(v.currentTime,4);assert.equal(v.paused,false);assert.equal(v.playbackRate,1);assert.equal(v.muted,false);
});
test('manual source volume changes while ducked become the restoration baseline',()=>{
  const v=new Video(),duck=new SourceVolume(()=>0);
  duck.command({active:true,percent:20});duck.tick(v);v.volume=.8;near(v.volume,.16);
  duck.command({active:false});near(v.volume,.8);
});
test('lost native heartbeat restores volume even while a stale speech flag is true',()=>{
  let now=0;const v=new Video(),duck=new SourceVolume(()=>now);
  duck.command({active:true,percent:20});duck.tick(v);near(v.volume,.12);
  now=1501;duck.tick(v);near(v.volume,.6);assert.equal(duck.video,null);
});
test('changing the selected video restores the old source and leases only the new source',()=>{
  const v=new Video(.6),other=new Video(.4),duck=new SourceVolume(()=>0);
  duck.command({active:true,percent:20});duck.tick(v);duck.tick(other);
  near(v.volume,.6);near(other.volume,.08);duck.restore();near(other.volume,.4);
});
test('muted source stays muted and missing video or invalid commands restore volume',()=>{
  const v=new Video(),duck=new SourceVolume(()=>0);v.muted=true;
  for(const invalid of [null,{active:true,percent:0},{active:true,percent:101},{active:true,percent:'20'}]){
    duck.command({active:true,percent:20});duck.tick(v);near(v.volume,.12);
    duck.command(invalid);near(v.volume,.6);assert.equal(v.muted,true);
  }
  duck.command({active:true,percent:20});duck.tick(v);duck.tick(null);near(v.volume,.6);
});
test('a pending manual adjustment is not overwritten on restore',()=>{
  const v=new Video(),duck=new SourceVolume(()=>0);
  duck.command({active:true,percent:20});duck.tick(v);
  v._volume=.9;duck.restore();near(v.volume,.9);
});
