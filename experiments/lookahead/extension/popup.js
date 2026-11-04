(()=>{
  'use strict';
  const $=id=>document.getElementById(id),send=data=>chrome.runtime.sendMessage(data);
  const t=value=>globalThis.ELTLocale?.text(value)||value;
  let options={},ttsVoices=[],systemVoices=[],desired={},pending={},saving=false,ready=false,canTranslate=false,volumeTimer;
  function note(text,error=false){$('message').textContent=t(text);$('message').className='message'+(error?' error':'');}
  function status(text,connected=false,error=false){$('status').textContent=t(text);$('dot').className='dot'+(error?' error':connected?' ready':'');}
  function render(){
    const value={...options,...desired},system=value.speech_engine==='system';
    $('narrate').checked=!!value.narrate;$('narrate').disabled=!canTranslate;
    $('model').value=system?'system':'qwen:'+(value.tts_model||'0.6B');
    const voices=system?systemVoices:ttsVoices,wanted=String(system?value.voice:value.tts_voice);
    $('voice').replaceChildren();
    for(const item of voices){const node=document.createElement('option');node.value=String(item.id);node.textContent=item.label;$('voice').append(node);}
    $('voice').value=voices.some(v=>String(v.id)===wanted)?wanted:String(voices[0]?.id??'');
    $('voice').disabled=!voices.length;$('voice').title=voices.find(v=>String(v.id)===$('voice').value)?.label||'没有可用的中文音色';
    $('model').querySelector('option[value="system"]').disabled=!systemVoices.length;
    $('speed').value=Number(value.base_speed||1).toFixed(2);$('volume').value=value.volume??80;$('volumeValue').textContent=$('volume').value+'%';
    $('duck').checked=value.duck_source!==false;$('source').value=value.source_percent??20;$('source').disabled=!$('duck').checked;
    $('captionWidth').value=value.caption_width??92;$('captionHeight').value=value.caption_height??180;$('captionFont').value=value.caption_font_size??18;
    globalThis.ELTLocale?.translateDocument();
  }
  async function flush(){
    if(saving||!ready||!Object.keys(pending).length)return;
    const changes=pending;pending={};saving=true;note('正在应用设置…');
    try{
      const result=await send({kind:'ELT_SET_PLAYBACK',options:changes});
      if(result?.error)throw Error(result.error);
      if(!result?.playback)throw Error('设置未获得确认，请重新打开扩展。');
      options=result.playback;
      for(const key of Object.keys(changes))if(desired[key]===changes[key])delete desired[key];
      note(result.warning||(result.session_id?'已应用到当前课程。':'已保存，下次开始时使用。'),!!result.warning);
    }catch(error){
      for(const key of Object.keys(changes))if(desired[key]===changes[key])delete desired[key];
      note(error.message||'设置未应用，请检查 ELT 连接。',true);
    }finally{saving=false;render();if(Object.keys(pending).length)flush();}
  }
  function queue(changes){if(!ready)return;Object.assign(desired,changes);Object.assign(pending,changes);flush();}
  $('narrate').onchange=()=>queue({narrate:$('narrate').checked});
  $('model').onchange=()=>{
    const system=$('model').value==='system',size=$('model').value.split(':')[1];
    const changes={speech_engine:system?'system':'qwen',...(system?{}:{tts_model:size})};
    Object.assign(desired,changes);render();
    if(system)changes.voice=Number($('voice').value);else changes.tts_voice=$('voice').value;
    queue(changes);
  };
  $('voice').onchange=()=>queue((desired.speech_engine||options.speech_engine)==='system'?{voice:Number($('voice').value)}:{tts_voice:$('voice').value});
  $('speed').onchange=()=>{
    const value=Number($('speed').value);if(!Number.isFinite(value)||value<1||value>2){note('基础语速范围为 1.00–2.00 倍。',true);render();return;}queue({base_speed:value});
  };
  $('volume').oninput=()=>{const value=Number($('volume').value);desired.volume=value;$('volumeValue').textContent=value+'%';clearTimeout(volumeTimer);volumeTimer=setTimeout(()=>queue({volume:value}),150);};
  $('volume').onchange=()=>{clearTimeout(volumeTimer);queue({volume:Number($('volume').value)});};
  $('duck').onchange=()=>{queue({duck_source:$('duck').checked});$('source').disabled=!$('duck').checked;};
  $('source').onchange=()=>{
    const value=Number($('source').value);if(!Number.isInteger(value)||value<10||value>100){note('原声保留范围为 10%–100%。',true);render();return;}queue({source_percent:value});
  };
  for(const [id,key,min,max] of [['captionWidth','caption_width',30,100],['captionHeight','caption_height',64,600],['captionFont','caption_font_size',8,48]]){
    $(id).onchange=()=>{const value=Number($(id).value);if(!Number.isInteger(value)||value<min||value>max){note('请在输入框标示的范围内调整字幕。',true);render();return;}queue({[key]:value});};
  }
  $('start').onclick=async()=>{
    $('start').disabled=true;status('正在连接当前课程页…');
    try{
      const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
      const result=await send({kind:'ELT_ACTIVATE_TAB',tabId:tab?.id,language:$('language').value});
      if(result?.error)throw Error(result.error);
      status(result.active?(result.status==='ready'?'字幕跟随中。':'已连接，正在准备字幕。'):'尚未开始，请检查 ELT 连接。',!!result.active);
    }catch(error){status(error.message||'无法连接扩展，请刷新课程页后重试。',false,true);}
    finally{$('start').disabled=false;}
  };
  $('stop').onclick=async()=>{
    try{const result=await send({kind:'ELT_STOP_TAB'});if(result?.error)throw Error(result.error);status('字幕和朗读已停止，原视频继续播放。',true);}
    catch(error){status(error.message||'无法联系扩展，请检查 ELT 连接。',false,true);}
  };
  (async()=>{
    try{
      const connection=await send({kind:'ELT_STATUS'});
      globalThis.ELTLocale?.setLanguage(connection.ui_language||'zh');globalThis.ELTLocale?.translateDocument();
      status(connection.error||(connection.active?'字幕跟随中。':connection.paired?'已连接 ELT，选择课程语言后开始。':'请先在 ELT 主程序启动网页模式并连接扩展。'),!!connection.paired,!!connection.error);
      if(connection.language)$('language').value=connection.language;
      if(!connection.paired)return;
      const result=await send({kind:'ELT_GET_READING'});if(result?.error)throw Error(result.error);
      options=result.playback;ttsVoices=result.tts_voices||[];systemVoices=result.voices||[];canTranslate=!!result.translate;
      globalThis.ELTLocale?.setLanguage(result.ui_language||options.ui_language||'zh');
      if(result.language)$('language').value=result.language;ready=true;$('reading').disabled=false;$('captions').disabled=false;render();
      note(canTranslate?'设置即时应用；更换模型或音色需要准备时间。':'请在 ELT 主程序启用翻译后使用朗读。');
    }catch(error){note(error.message||'无法读取设置，请更新 ELT 后重新连接扩展。',true);}
  })();
})();
