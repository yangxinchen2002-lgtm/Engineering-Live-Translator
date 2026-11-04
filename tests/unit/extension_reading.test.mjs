import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const script=fs.readFileSync(new URL('../../app/web_follow/extension/popup.js',import.meta.url),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const defaults={narrate:true,speech_engine:'qwen',tts_model:'1.7B',tts_voice:'lecture_male',voice:7,
  volume:80,base_speed:1,duck_source:true,source_percent:20,speech_revision:0,playback_revision:0};
async function fixture(save,translate=true){
  const ids=['status','dot','message','language','start','stop','reading','narrate','model','voice','speed','volume','volumeValue','duck','source','captions','captionWidth','captionHeight','captionFont'];
  const node=()=>({disabled:false,children:[],value:'',checked:false,textContent:'',querySelector(){return {};},
    replaceChildren(){this.children=[];},append(child){this.children.push(child);}});
  const elements=Object.fromEntries(ids.map(id=>[id,node()]));elements.reading.disabled=true;
  const timers=new Map();let serial=0;const requests=[];
  const context=vm.createContext({document:{getElementById:id=>elements[id],createElement:node},
    setTimeout:fn=>{timers.set(++serial,fn);return serial;},clearTimeout:id=>timers.delete(id),
    chrome:{tabs:{query:async()=>[{id:42}]},runtime:{sendMessage:async message=>{
      if(message.kind==='ELT_STATUS')return {paired:true};
      if(message.kind==='ELT_GET_READING')return {playback:{...defaults},translate,language:'en',
        tts_voices:[{id:'lecture_male',label:'讲课男声 · Aiden（试用）'},{id:'serena',label:'Serena'}],
        voices:[{id:7,label:'Windows 中文音色'}]};
      requests.push(message);return save?save(message):{playback:{...defaults,...message.options},session_id:'s'};
    }}}});
  vm.runInContext(script,context);await flush();
  return {elements,requests,runTimers(){const jobs=[...timers.values()];timers.clear();for(const fn of jobs)fn();}};
}
test('popup loads existing app settings and retains the full selected voice label',async()=>{
  const {elements:e}=await fixture();assert.equal(e.reading.disabled,false);assert.equal(e.model.value,'qwen:1.7B');
  assert.equal(e.voice.value,'lecture_male');assert.match(e.voice.title,/Aiden/);assert.equal(e.speed.value,'1.00');
  assert.equal(Number(e.source.value),20);assert.equal(e.narrate.checked,true);
});

test('caption controls are usable without translation and send validated changes',async()=>{
  const f=await fixture(undefined,false),e=f.elements;
  assert.equal(e.captions.disabled,false);e.captionWidth.value='65';e.captionWidth.onchange();await flush();
  assert.equal(f.requests.at(-1).options.caption_width,65);
  e.captionHeight.value='120';e.captionHeight.onchange();await flush();assert.equal(f.requests.at(-1).options.caption_height,120);
  e.captionFont.value='7';const count=f.requests.length;e.captionFont.onchange();await flush();assert.equal(f.requests.length,count);
});
test('rapid changes use one active request and a newer value is not replaced by the earlier reply',async()=>{
  const finishes=[];let active=0,maximum=0;
  const f=await fixture(message=>{maximum=Math.max(maximum,++active);return new Promise(resolve=>finishes.push(value=>{active--;resolve(value);}));});
  f.elements.source.value='35';f.elements.source.onchange();
  f.elements.source.value='40';f.elements.source.onchange();assert.equal(f.requests.length,1);
  finishes[0]({playback:{...defaults,source_percent:35,playback_revision:1},session_id:'s'});await flush();
  assert.equal(Number(f.elements.source.value),40);assert.equal(f.requests.length,2);assert.equal(f.requests[1].options.source_percent,40);
  finishes[1]({playback:{...defaults,source_percent:40,playback_revision:2},session_id:'s'});await flush();assert.equal(maximum,1);
});
test('a reply for another field cannot erase a volume drag waiting for its debounce',async()=>{
  let finish;const f=await fixture(message=>new Promise(resolve=>finish=resolve));
  f.elements.source.value='35';f.elements.source.onchange();f.elements.volume.value='25';f.elements.volume.oninput();
  finish({playback:{...defaults,source_percent:35},session_id:'s'});await flush();
  assert.equal(Number(f.elements.volume.value),25);f.runTimers();assert.equal(f.requests.at(-1).options.volume,25);
  finish({playback:{...defaults,volume:25},session_id:'s'});await flush();
});
test('a rejected setting reverts to the known value and has an explicit error',async()=>{
  const f=await fixture(async()=>({error:'test-only setting rejected'}));
  f.elements.speed.value='1.3';f.elements.speed.onchange();await flush();
  assert.equal(f.elements.speed.value,'1.00');assert.match(f.elements.message.textContent,/rejected/);
  assert.match(f.elements.message.className,/error/);
});
test('changing engine sends a real system voice identity and local choices retain their identities',async()=>{
  const f=await fixture();f.elements.model.value='system';f.elements.model.onchange();await flush();
  assert.equal(f.requests.at(-1).options.speech_engine,'system');assert.equal(f.requests.at(-1).options.voice,7);
  f.elements.model.value='qwen:0.6B';f.elements.model.onchange();await flush();
  assert.equal(f.requests.at(-1).options.tts_model,'0.6B');assert.equal(f.requests.at(-1).options.tts_voice,'lecture_male');
});
test('narration cannot be enabled by the popup when app translation is disabled',async()=>{
  const {elements:e}=await fixture(undefined,false);assert.equal(e.narrate.disabled,true);assert.match(e.message.textContent,/启用翻译/);
});
