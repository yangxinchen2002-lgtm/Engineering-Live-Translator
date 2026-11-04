(()=>{
  if(!document.querySelector('meta[name="elt-lookahead"][content="2"]'))return;
  const button=document.getElementById('pairBridge');if(!button)return;
  const t=value=>{globalThis.ELTLocale?.setLanguage(document.getElementById('ui_language')?.value||'zh');return globalThis.ELTLocale?.text(value)||value;};
  const messenger=ELTRuntime.createMessenger(chrome.runtime,()=>{
    delete button.dataset.extensionReady;button.disabled=true;
    button.textContent=t('扩展已更新，请刷新本设置页后重新连接');
  });
  button.dataset.extensionReady='true';button.textContent=t('连接网页跟随扩展');
  button.addEventListener('click',async event=>{
    if(!event.isTrusted)return;
    event.stopImmediatePropagation();button.disabled=true;
    const value=id=>document.getElementById(id)?.value;
    try{
      const result=await messenger.send({kind:'ELT_PAIR',url:location.href,options:{language:value('language'),
        lookahead:Number(value('lookahead')),provider:value('provider'),model:value('model'),voice:Number(value('voice')),
        translate:document.getElementById('translate').checked,narrate:document.getElementById('narrate').checked,
        target_language:value('target_language')||'zh',ui_language:value('ui_language')||'zh'}});
      if(result?.error)throw Error(result.error);
      button.textContent=t('已配对：打开课程页，点击扩展开始');
    }catch{if(messenger.valid)button.textContent=t('配对失败，请确认实验服务正在运行');}
    finally{button.disabled=!messenger.valid;}
  },true);
})();
