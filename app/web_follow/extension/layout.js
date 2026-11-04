// Actual DOM measurements; no ellipsis or character-count truncation.
(function(scope){
  'use strict';
  const cache=new WeakMap();
  const captionCSS=':host{position:fixed;z-index:2147483646;pointer-events:none;font-family:"Segoe UI","Microsoft YaHei",sans-serif}:host([hidden]){display:none!important}section{position:relative;box-sizing:border-box;max-height:inherit;overflow:auto;pointer-events:auto;background:#101924df;border:1px solid #49617970;border-radius:10px;padding:6px 30px 6px 12px;color:#f3f6fc;text-align:center}p{margin:0}.elt-source,.elt-translation{display:block;white-space:normal;overflow-wrap:anywhere;word-break:normal;line-height:1.45;max-width:100%;margin:1px 0;text-align:center}.elt-source{color:#f3f6fc}.elt-translation{color:#ffe5a3}p[hidden],button[hidden]{display:none}button{position:absolute;right:4px;top:3px;pointer-events:auto;width:22px;height:22px;padding:0;border:0;border-radius:5px;background:transparent;color:#bac8da;font:18px/22px "Segoe UI",sans-serif;cursor:pointer}button:hover{background:#ffffff20;color:white}#elt-unlock{right:28px;font-size:14px}section::-webkit-scrollbar{width:4px}section::-webkit-scrollbar-thumb{background:#6d7f95;border-radius:4px}';
  const captionMarkup='<section><p id="o" class="elt-source"></p><p id="t" class="elt-translation"></p></section><button id="elt-close" title="停止字幕" aria-label="停止字幕">×</button><button id="elt-unlock" title="允许中文朗读" aria-label="允许中文朗读" hidden>🔊</button>';
  function captionSettings(value={}){
    const bounded=(key,fallback,min,max)=>Number.isFinite(value[key])?Math.max(min,Math.min(max,value[key])):fallback;
    return {width:bounded('caption_width',92,30,100),height:bounded('caption_height',180,64,600),font:bounded('caption_font_size',18,8,48)};
  }
  function placeCaption(host,rect,options={},viewport={width:innerWidth,height:innerHeight}){
    const settings=captionSettings(options),width=Math.max(80,Math.min(viewport.width-20,rect.width*settings.width/100));
    host.style.left=Math.max(10,Math.min(viewport.width-width-10,rect.left+(rect.width-width)/2))+'px';
    host.style.width=width+'px';host.style.right='auto';
    host.style.bottom=Math.max(12,viewport.height-rect.bottom+44)+'px';
    host.style.maxHeight=Math.max(48,Math.min(settings.height,rect.height*.7,viewport.height-60))+'px';
  }
  function renderCaption(host,original,translated,unlock,cue,options={}){
    const english=options.ui_language==='en',close=unlock.parentNode?.querySelector('#elt-close');
    if(close){close.title=english?'Stop subtitles':'停止字幕';close.setAttribute('aria-label',close.title);}
    unlock.title=english?'Allow narration':'允许朗读';unlock.setAttribute?.('aria-label',unlock.title);
    original.textContent=cue?.source||'';translated.textContent=cue?.translation||'';
    original.hidden=!original.textContent;translated.hidden=!translated.textContent;
    host.hidden=!(original.textContent||translated.textContent||!unlock.hidden);
    if(!host.hidden){const settings=captionSettings(options);fitCaption(original,Math.max(8,settings.font-2),8);fitCaption(translated,settings.font,8);}
  }
  function fitCaption(element,maxSize=18,minSize=10,maxLines=2){
    const width=Math.round(element.getBoundingClientRect().width);
    if(!width||!element.textContent)return null;
    const key=element.textContent+'\n'+width+':'+maxSize+':'+minSize+':'+maxLines;
    const previous=cache.get(element);if(previous?.key===key)return previous.result;
    element.style.lineHeight='1.45';
    element.style.whiteSpace='normal';element.style.overflowWrap='anywhere';
    element.style.fontSize=maxSize+'px';
    const fits=size=>element.scrollHeight<=size*1.45*maxLines+1;
    let chosen=maxSize;
    if(!fits(maxSize)){
      let low=minSize,high=maxSize;chosen=minSize;element.style.fontSize=minSize+'px';
      if(fits(minSize)){
        while(high-low>.5){
          const mid=Math.floor((low+high)*2)/4;element.style.fontSize=mid+'px';
          if(fits(mid)){chosen=mid;low=mid;}else high=mid;
        }
      }
      element.style.fontSize=chosen+'px';
    }
    // If even the minimum exceeds two lines, retain the entire text and let it
    // wrap further. Never hide an untranslated tail just to enforce a line cap.
    const result={fontSize:chosen,lines:Math.ceil((element.scrollHeight-1)/(chosen*1.45)),fits:fits(chosen)};
    cache.set(element,{key,result});return result;
  }
  scope.ELTFollow={...scope.ELTFollow,captionCSS:captionCSS+'section{overscroll-behavior:contain}',captionMarkup,captionSettings,placeCaption,renderCaption,fitCaption};
})(globalThis);
