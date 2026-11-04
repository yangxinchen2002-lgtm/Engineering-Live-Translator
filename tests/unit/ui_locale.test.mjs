import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const script=fs.readFileSync(new URL('../../app/web_follow/extension/ui-locale.js',import.meta.url),'utf8');

function fixture(){
  const node=(value,content=false)=>({nodeValue:value,parentElement:{closest:()=>content?{}:null}});
  const title=node('开始字幕'),source=node('开始字幕',true),translation=node('字幕是课程内容。',true);
  const document={documentElement:{},querySelectorAll:()=>[],createTreeWalker(){
    let index=0;const nodes=[title,source,translation];return {nextNode(){this.currentNode=nodes[index++];return !!this.currentNode;}};
  }};
  const scope={document,NodeFilter:{SHOW_TEXT:4}};vm.runInNewContext(script,scope);
  return {locale:scope.ELTLocale,document,title,source,translation};
}

test('English interface localization preserves source and translated subtitle data',()=>{
  const f=fixture();f.locale.setLanguage('en');f.locale.translateDocument();
  assert.equal(f.title.nodeValue,'Start subtitles');assert.equal(f.source.nodeValue,'开始字幕');
  assert.equal(f.translation.nodeValue,'字幕是课程内容。');assert.equal(f.document.documentElement.lang,'en');
});

test('repeated localization preserves English text and can restore Chinese labels',()=>{
  const f=fixture();f.locale.setLanguage('en');f.locale.translateDocument();f.locale.translateDocument();
  assert.equal(f.title.nodeValue,'Start subtitles');
  f.title.nodeValue='停止字幕';f.locale.translateDocument();assert.equal(f.title.nodeValue,'Stop subtitles');
  f.locale.setLanguage('zh');f.locale.translateDocument();assert.equal(f.title.nodeValue,'停止字幕');
});

test('dynamic service messages use the English catalogue and both bundles match',()=>{
  const f=fixture();f.locale.setLanguage('en');
  assert.equal(f.locale.text('字幕和朗读已停止，原视频继续播放。'),'Subtitles and narration stopped. The original video continues playing.');
  assert.equal(f.locale.text('已跟随原网页：15 秒 · 已预读至 30 秒 · 字幕 3 条'),'Following web player: 15 s · Prepared through 30 s · Subtitles 3 items');
  assert.equal(script,fs.readFileSync(new URL('../../app/web_follow/web/ui-locale.js',import.meta.url),'utf8'));
});
