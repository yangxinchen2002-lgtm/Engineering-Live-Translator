const button=document.getElementById('pairBridge'),notice=document.getElementById('notice');
const token=location.hash.slice(1);
const t=value=>globalThis.ELTLocale?.text(value)||value;
globalThis.ELTLocale?.translateDocument();
try{
  const response=await fetch('/api/settings',{headers:{'X-ELT-Lab-Token':token}});
  if(!response.ok)throw Error('connection unavailable');
  const settings=await response.json(),d=settings.defaults||{};
  globalThis.ELTLocale?.setLanguage(d.ui_language||'zh');globalThis.ELTLocale?.translateDocument();
  for(const key of ['language','provider','model','voice','lookahead','target_language','ui_language'])document.getElementById(key).value=d[key]??'';
  document.getElementById('translate').checked=!!d.translate;document.getElementById('narrate').checked=!!d.narrate;
  document.getElementById('summary').textContent=`${t(settings.languages[d.language]||'自动检测')} → ${t(d.target_language==='en'?'英语':'中文')} · ${t(d.translate?'翻译已启用':'仅原文')} · ${t(d.narrate?(d.speech_engine==='qwen'?'本地 Qwen TTS':'系统朗读'):'朗读关闭')} · ${d.lookahead} ${t('秒')}`;
  button.disabled=false;notice.textContent=t('点击绿色按钮完成连接，然后回课程页开始跟随。');
}catch{notice.textContent=t('本机服务连接不可用，请回到 ELT 主程序重新启动网页视频预读。');}
button.addEventListener('click',()=>{if(!button.dataset.extensionReady)notice.textContent=t('尚未发现网页扩展。请在 ELT 主程序打开扩展文件夹，安装或重新加载扩展后刷新本页。');});
