(()=>{
  'use strict';
  const t=value=>globalThis.ELTLocale?.text(value)||value;
  globalThis.ELTLocale?.setLanguage(globalThis.__eltUiLanguage||'zh');globalThis.ELTLocale?.translateDocument();
  const video=document.getElementById('video'),hint=document.getElementById('hint');
  const token=location.pathname.split('/')[2];
  fetch('info.json').then(r=>r.json()).then(value=>{document.getElementById('name').textContent=value.name;}).catch(()=>{});
  video.addEventListener('loadedmetadata',()=>{hint.textContent=t('视频已打开，可先准备字幕，再使用下方播放按钮。');});
  video.addEventListener('play',()=>{hint.hidden=true;});
  video.addEventListener('error',()=>{
    hint.hidden=false;hint.textContent=t('无法播放此文件。请检查文件是否仍可读取；内置播放器优先支持 H.264 / AAC 的 MP4，其他编码可用 VLC 应用音频模式。');
    window.__eltPlayer?.mediaError(video.error?.code||0);
  });
  // Only these explicit user controls change the original player's rate/fullscreen.
  document.getElementById('rate').onchange=event=>{video.playbackRate=Number(event.target.value);};
  document.getElementById('fullscreen').onclick=()=>{
    const viewer=document.getElementById('viewer');
    (document.fullscreenElement?document.exitFullscreen():viewer.requestFullscreen()).catch(()=>{});
  };
  video.src='/m/'+token;video.load();
})();
