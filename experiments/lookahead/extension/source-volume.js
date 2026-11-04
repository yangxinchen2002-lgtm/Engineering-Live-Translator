// Shared temporary lease on the selected video's volume, never its clock.
(function(scope){
  'use strict';
  class SourceVolume {
    constructor(now=()=>performance.now()) {
      this.now=now;this.video=null;this.base=null;this.applied=null;
      this.active=false;this.percent=20;this.until=0;
      this.changed=()=>{
        if(!this.video||this.applied===null)return;
        const actual=this.video.volume;
        if(Number.isFinite(actual)&&Math.abs(actual-this.applied)>.00001){
          // A manual volume change becomes the new unducked baseline.
          this.base=actual;this.tick(this.video);
        }
      };
    }
    command(value) {
      this.active=value?.active===true&&Number.isInteger(value.percent)&&value.percent>=10&&value.percent<=100;
      if(this.active)this.percent=value.percent;
      this.until=this.now()+1500;
      if(!this.active)this.restore();
    }
    restore() {
      const video=this.video,base=this.base,applied=this.applied;
      this.video=null;this.base=this.applied=null;
      if(!video)return;
      video.removeEventListener?.('volumechange',this.changed);
      // Do not overwrite a newer manual adjustment that has not been observed.
      if(applied!==null&&Math.abs(video.volume-applied)<=.00001)video.volume=base;
    }
    tick(video) {
      if(!this.active||this.now()>this.until||!video||video.isConnected===false||
          !Number.isFinite(video.volume)||video.volume<0||video.volume>1){this.restore();return;}
      if(video!==this.video){
        this.restore();this.video=video;this.base=video.volume;
        video.addEventListener?.('volumechange',this.changed);
      }else if(this.applied!==null&&Math.abs(video.volume-this.applied)>.00001)this.base=video.volume;
      const target=this.base*this.percent/100;
      this.applied=target;
      if(Math.abs(video.volume-target)>.00001)video.volume=target;
    }
  }
  scope.ELTFollow.SourceVolume=SourceVolume;
})(globalThis);
