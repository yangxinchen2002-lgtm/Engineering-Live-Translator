// Shared by the extension, standalone player and dependency-free Node tests.
(function (scope) {
  'use strict';
  const PAGE_HOSTS = new Set(['live.rbg.tum.de', 'www.moodle.tum.de', 'moodle.tum.de', 'video.opencast.tum.de']);
  const MEDIA_HOSTS = new Set(['edge.live.rbg.tum.de', 'video.opencast.tum.de']);
  function pageAllowed(value) {
    try {const u=new URL(value); return u.protocol==='https:' && PAGE_HOSTS.has(u.hostname) && !u.username && !u.password;} catch {return false;}
  }
  function mediaAllowed(value) {
    try {const u=new URL(value);return u.protocol==='https:' && MEDIA_HOSTS.has(u.hostname) && !u.username && !u.password && /\.(mp4|m3u8)$/i.test(u.pathname);} catch {return false;}
  }
  function discover(video, resources=[]) {
    const direct=video && (video.currentSrc || video.src);
    if (mediaAllowed(direct)) return direct;
    // Use the selected player's own source before unrelated resource entries.
    try{
      const container=video?.closest?.('.video-js');
      const player=video?.player||container?.player||scope.videojs?.getPlayer?.(container?.id);
      const bound=player?.currentSource?.()?.src;
      if(mediaAllowed(bound))return bound;
      for(const source of video?.querySelectorAll?.('source')||[])if(mediaAllowed(source.src))return source.src;
    }catch{}
    // Resource timing contains only this document's own loaded resources.
    return resources.map(x=>typeof x==='string'?x:x.name).find(x=>mediaAllowed(x)&&new URL(x).pathname.endsWith('.m3u8')) || '';
  }
  const clockOwners=new WeakMap();
  function clockVideo(videos,fallback) {
    const playable=[...videos].filter(v=>Number.isFinite(v.duration)&&v.duration>0);
    const audible=playable.filter(v=>v.muted===false&&Number.isFinite(v.volume)&&v.volume>0);
    const decoded=(audible.length?audible:playable).filter(v=>Number.isFinite(v.webkitAudioDecodedByteCount)&&v.webkitAudioDecodedByteCount>0);
    const previous=clockOwners.get(fallback);
    const chosen=audible.length===1?audible[0]:decoded.length===1?decoded[0]:playable.includes(previous)?previous:fallback;
    if(fallback&&chosen)clockOwners.set(fallback,chosen);return chosen;
  }
  function activeCue(cues,time) {return [...cues].reverse().find(c=>c.start<=time && time<c.end)||null;}
  function fitRate(duration,available,videoRate=1,maxRate=4,baseRate=1) {
    if (![duration,available,videoRate,maxRate].every(Number.isFinite) || available<=0 || duration<0 || videoRate<=0) return {rate:4,fits:false};
    const required=duration*videoRate/available;
    return {rate:Math.max(baseRate,Math.min(maxRate,required)),fits:required<=maxRate,required};
  }
  class Narrator {
    constructor(audio, load, report=()=>{}) {
      this.audio=audio;this.load=load;this.report=report;this.epoch=0;this.current=null;this.pending=null;
      this.finished=new Set();this.session='';this.url='';this.preloaded=null;this.sentenceRate=1;this.sourceRate=1;
      this.blocked=false;this.baseRate=1;
      this.enabled=true;
      this.speechRevision=0;
      audio.preservesPitch=true;
      audio.addEventListener('ended',()=>{if(audio.ended&&this.current){this.finished.add(this.current.id);this.current=null;
        if(this.url){URL.revokeObjectURL(this.url);this.url='';}}});
    }
    cancel(reason='reset') {
      this.epoch++;this.audio.pause();this.audio.removeAttribute('src');this.audio.load();
      if(this.url){URL.revokeObjectURL(this.url);this.url='';}
      this.discardPreload();
      this.current=this.pending=null;
      this.blocked=false;
      if(reason==='reset')this.finished.clear();
    }
    discardPreload() {
      const entry=this.preloaded;this.preloaded=null;
      if(entry){entry.discarded=true;if(entry.url?.startsWith('blob:'))URL.revokeObjectURL(entry.url);}
    }
    setOptions(options={}) {
      if(Number.isInteger(options.speech_revision)&&options.speech_revision!==this.speechRevision){
        this.cancel();this.speechRevision=options.speech_revision;
      }
      if(typeof options.narrate==='boolean'&&options.narrate!==this.enabled){
        this.enabled=options.narrate;
        if(!this.enabled){if(this.current)this.finished.add(this.current.id);this.cancel('disabled');}
      }
      if(Number.isFinite(options.volume)&&options.volume>=0&&options.volume<=100)this.audio.volume=options.volume/100;
      if(Number.isFinite(options.base_speed)&&options.base_speed>=1&&options.base_speed<=2&&options.base_speed!==this.baseRate){
        this.baseRate=options.base_speed;this.sourceRate=0;
      }
    }
    prefetch(cues,clock) {
      if(clock.seeking||!this.enabled)return;
      const next=cues.find(c=>c.speech&&c.start>clock.time&&c.start-clock.time<=8&&!this.finished.has(c.id));
      if(this.preloaded?.id===next?.id)return;
      this.discardPreload();if(!next)return;
      const entry={id:next.id,discarded:false,url:''};this.preloaded=entry;
      // At most one future file, no playback before its source time.
      entry.promise=Promise.resolve().then(()=>this.load(next)).then(url=>{
        if(entry.discarded){if(url.startsWith('blob:'))URL.revokeObjectURL(url);return {error:Error('expired prefetch')};}
        entry.url=url;return {url};
      },error=>({error}));
    }
    update(cues,clock,session) {
      if(session!==this.session || clock.seeking) {
        this.cancel();this.session=session;
      }
      if(!this.enabled)return;
      const allowed=new Set(cues.map(c=>c.id));this.finished=new Set([...this.finished].filter(x=>allowed.has(x)));
      const cue=activeCue(cues,clock.time);
      if(this.current && (clock.time>=this.current.end || !cue || cue.id!==this.current.id)) {
        const old=this.current;const incomplete=!this.audio.ended && this.audio.currentTime+.08<this.audio.duration;
        this.finished.add(old.id);this.cancel('deadline');
        if(incomplete)this.report('deadline',old);
      }
      if(clock.paused || clock.seeking) {this.audio.pause();return;}
      if(this.current) {
        // Normal speed is the floor. Re-evaluate only after a user changes the
        // video's speed; a short translation should finish early and wait.
        if(Math.abs(clock.rate-this.sourceRate)>.001){
          const duration=Number.isFinite(this.audio.duration)?this.audio.duration:this.current.speech_seconds;
          const remaining=Math.max(0,duration-this.audio.currentTime);
          const fit=fitRate(remaining,this.current.end-clock.time,clock.rate,4,this.baseRate);
          this.sentenceRate=fit.rate;this.sourceRate=clock.rate;
          if(!fit.fits)this.report('fast',this.current);
        }
        if(Math.abs(this.sentenceRate-this.audio.playbackRate)>.001)this.audio.playbackRate=this.sentenceRate;
        if(this.audio.paused&&!this.audio.ended&&!this.blocked)this.audio.play().catch(()=>{this.blocked=true;this.report('permission',this.current);});
      } else if(cue?.speech && !this.pending && !this.finished.has(cue.id)) this.start(cue,clock);
    }
    async start(cue,clock) {
      const epoch=this.epoch;this.pending=cue;
      try {
        let url;
        if(this.preloaded?.id===cue.id){
          const entry=this.preloaded;this.preloaded=null;
          const result=await entry.promise;if(result.error)throw result.error;url=result.url;
        }else url=await this.load(cue);
        if(epoch!==this.epoch){if(url.startsWith('blob:'))URL.revokeObjectURL(url);return;}
        // Fetch may finish after the source has advanced. Re-check against the newest clock.
        const now=this.lastClock || clock;
        if(now.time>=cue.end||now.time<cue.start||now.seeking){if(url.startsWith('blob:'))URL.revokeObjectURL(url);this.finished.add(cue.id);if(now.time>=cue.end)this.report('deadline',cue);return;}
        if(this.url)URL.revokeObjectURL(this.url);
        this.current=cue;this.pending=null;this.audio.src=url;this.url=url.startsWith('blob:')?url:'';
        const fit=fitRate(cue.speech_seconds,cue.end-now.time,now.rate,4,this.baseRate);
        this.sentenceRate=fit.rate;this.sourceRate=now.rate;this.audio.playbackRate=fit.rate;
        if(!fit.fits)this.report('fast',cue);
        if(!now.paused)await this.audio.play();
        if(epoch!==this.epoch)this.audio.pause();
      } catch(error) {if(epoch===this.epoch){
        if(error?.name==='NotAllowedError'&&this.current){this.blocked=true;this.report('permission',cue);}
        else{this.finished.add(cue.id);this.current=this.pending=null;this.report('unavailable',cue);}
      }}
      finally {if(epoch===this.epoch)this.pending=null;}
    }
    tick(cues,clock,session) {this.lastClock=clock;this.update(cues,clock,session);this.prefetch(cues,clock);}
  }
  scope.ELTFollow={pageAllowed,mediaAllowed,discover,clockVideo,activeCue,fitRate,Narrator};
})(globalThis);
