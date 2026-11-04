"""Backlog-driven tempo with a grace period, hysteresis and bounded slew rate."""
import math


class CatchUpPacer:
    def __init__(self,start_chars=80,grace_seconds=5):
        if type(start_chars) is not int or not 20<=start_chars<=1000:raise ValueError('invalid catch-up threshold')
        if type(grace_seconds) is not int or not 1<=grace_seconds<=30:raise ValueError('invalid catch-up grace period')
        self.start_chars=start_chars;self.grace_seconds=grace_seconds
        self.reset()

    def reset(self):
        self.active=False;self.above_since=None;self.below_since=None
        self.last_ns=None;self.multiplier=1.
        self.applied_speed=None;self.applied_base=None;self.applied_ns=None

    def update(self,characters,base_speed,enabled,now_ns):
        if type(characters) is not int or characters<0:raise ValueError('invalid pending character count')
        if type(base_speed) not in (int,float) or not math.isfinite(base_speed) or not .8<=base_speed<=2:raise ValueError('invalid base speed')
        if type(now_ns) is not int or now_ns<0:raise ValueError('invalid pacing clock')
        if self.last_ns is not None and now_ns<self.last_ns:raise ValueError('pacing clock moved backwards')
        elapsed=min(.5,(now_ns-self.last_ns)/1e9) if self.last_ns is not None else 0.
        self.last_ns=now_ns
        if not enabled:
            self.reset();return base_speed
        if not self.active:
            if characters>=self.start_chars:
                if self.above_since is None:self.above_since=now_ns
                if now_ns-self.above_since>=self.grace_seconds*1e9:
                    self.active=True;self.above_since=None
            else:self.above_since=None
        else:
            if characters<=self.start_chars//2:
                if self.below_since is None:self.below_since=now_ns
                if now_ns-self.below_since>=3e9:
                    self.active=False;self.below_since=None
            else:self.below_since=None
        lower=self.start_chars/2
        pressure=max(0,min(1,(characters-lower)/(3*self.start_chars-lower)))
        target=1+.5*pressure if self.active else 1.
        rate=.08 if target>self.multiplier else .10
        step=rate*elapsed
        self.multiplier=max(target,self.multiplier-step) if target<self.multiplier else min(target,self.multiplier+step)
        # Runtime atempo commands reset its waveform alignment origin. Give the
        # filter at least 200 ms between automatic changes instead of commanding
        # it on every 20 ms GUI tick; keep the same slew and relative speed cap.
        if (self.applied_ns is None or now_ns-self.applied_ns>=200_000_000 or self.applied_base!=base_speed):
            self.applied_speed=max(base_speed,min(base_speed*1.5,round(base_speed*self.multiplier,3)))
            self.applied_base=base_speed;self.applied_ns=now_ns
        return self.applied_speed
