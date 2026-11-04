import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import '../extension/runtime.js';
import '../extension/core.js';
import '../extension/source-volume.js';
const {createMessenger}=globalThis.ELTRuntime;
const source=name=>fs.readFileSync(new URL('../extension/'+name,import.meta.url),'utf8');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('synchronous invalidation becomes a handled rejection and invalidates only once',async()=>{
  let calls=0,cleanup=0;
  const messenger=createMessenger({id:'a',sendMessage(){calls++;throw Error('Extension context invalidated.');}},()=>cleanup++);
  let pending;assert.doesNotThrow(()=>{pending=messenger.send({kind:'test'});});
  await assert.rejects(pending,/invalidated/);
  await assert.rejects(messenger.send({kind:'again'}),/invalidated/);
  assert.equal(calls,1);assert.equal(cleanup,1);assert.equal(messenger.valid,false);
});
test('asynchronous invalidation stops further sends',async()=>{
  let cleanup=0;
  const messenger=createMessenger({id:'a',sendMessage:async()=>{throw Error('Extension context invalidated.');}},()=>cleanup++);
  await assert.rejects(messenger.send({}),/invalidated/);
  assert.equal(cleanup,1);assert.equal(messenger.valid,false);
});
test('concurrent in-flight failures run cleanup only once',async()=>{
  const rejects=[];let cleanup=0;
  const messenger=createMessenger({id:'a',sendMessage:()=>new Promise((_,reject)=>rejects.push(reject))},()=>cleanup++);
  const pending=Promise.allSettled([messenger.send({}),messenger.send({})]);
  for(const reject of rejects)reject(Error('Extension context invalidated.'));
  assert.ok((await pending).every(x=>x.status==='rejected'));assert.equal(cleanup,1);
});
test('missing or throwing runtime identity is handled before sending',async()=>{
  for(const runtime of [{id:undefined},{get id(){throw Error('Extension context invalidated.');}}]){
    let cleanup=0;
    const messenger=createMessenger(runtime,()=>cleanup++);
    await assert.rejects(messenger.send({}),/invalidated/);assert.equal(cleanup,1);
  }
});
test('ordinary connection failure stays retryable',async()=>{
  let cleanup=0,calls=0;
  const messenger=createMessenger({id:'a',sendMessage:async()=>{
    if(++calls===1)throw Error('Could not establish connection.');return {ok:true};
  }},()=>cleanup++);
  await assert.rejects(messenger.send({}),/establish/);
  assert.deepEqual(await messenger.send({}),{ok:true});assert.equal(cleanup,0);
});
test('the real registration callback stops every owned interval after context invalidation',async()=>{
  let invalid=false,cancelled=0,sends=0,serial=0;
  const timers=new Map(),events=new Map();
  const runtime={get id(){if(invalid)throw Error('Extension context invalidated.');return 'a';},
    sendMessage(){sends++;return Promise.resolve({});},onMessage:{addListener(){}}};
  const context=vm.createContext({chrome:{runtime},Audio:class{addEventListener(){}},
    document:{querySelectorAll:()=>[]},
    ELTFollow:{SourceVolume:globalThis.ELTFollow.SourceVolume,Narrator:class{cancel(){cancelled++;}}},
    setInterval:(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},
    clearInterval:id=>timers.delete(id),
    addEventListener:(name,fn)=>events.set(name,fn),removeEventListener:name=>events.delete(name)});
  vm.runInContext(source('runtime.js'),context);vm.runInContext(source('content.js'),context);await flush();
  assert.equal(timers.size,3);assert.equal(sends,1);
  const registration=[...timers.values()].find(x=>x.ms===3000).fn;invalid=true;
  assert.doesNotThrow(registration);await flush();
  assert.equal(timers.size,0);assert.equal(cancelled,1);assert.equal(events.size,0);
  registration();await flush();assert.equal(sends,1);
});
test('the real pairing page gives a refresh hint instead of a false service/key error',async()=>{
  let click;
  const button={dataset:{},textContent:'',disabled:false,addEventListener:(event,fn)=>{click=fn;}};
  const context=vm.createContext({location:{href:'http://127.0.0.1:1234/'},
    document:{querySelector:()=>({}),getElementById:id=>id==='pairBridge'?button:{value:'',checked:false}},
    chrome:{runtime:{id:'a',sendMessage(){throw Error('Extension context invalidated.');}}}});
  vm.runInContext(source('runtime.js'),context);vm.runInContext(source('pairing.js'),context);
  await click({isTrusted:true,stopImmediatePropagation(){}});
  assert.match(button.textContent,/刷新/);assert.equal(button.disabled,true);
  assert.equal(button.dataset.extensionReady,undefined);
});
