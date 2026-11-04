"""Provider-reported token accounting and versioned USD estimates, never billing data."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date,datetime,time,timedelta,timezone
from decimal import Decimal,InvalidOperation
import json
from pathlib import Path

TOKEN_FIELDS=('prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens')
PRICE_SOURCE='https://api-docs.deepseek.com/quick_start/pricing/'


def read_usage(value:dict) -> dict[str,int]:
    if not isinstance(value,dict):raise ValueError('invalid usage')
    fields={}
    for name in TOKEN_FIELDS:
        if name in value:
            if type(value[name]) is not int or not 0<=value[name]<=10**12:raise ValueError('invalid usage count')
            fields[name]=value[name]
    details=value.get('prompt_tokens_details')
    if isinstance(details,dict) and 'cached_tokens' in details:
        cached=details['cached_tokens']
        if type(cached) is not int or not 0<=cached<=10**12:raise ValueError('invalid cached tokens')
        if 'prompt_cache_hit_tokens' in fields and cached!=fields['prompt_cache_hit_tokens']:raise ValueError('inconsistent cache count')
        fields['prompt_cache_hit_tokens']=cached
    prompt,output=fields.get('prompt_tokens'),fields.get('completion_tokens')
    hit,miss=fields.get('prompt_cache_hit_tokens'),fields.get('prompt_cache_miss_tokens')
    if prompt is None and hit is not None and miss is not None:
        prompt=fields['prompt_tokens']=hit+miss
    if prompt is not None:
        if hit is not None and hit>prompt or miss is not None and miss>prompt:raise ValueError('cache exceeds input')
        if hit is not None and miss is not None and hit+miss!=prompt:raise ValueError('inconsistent cache total')
        if hit is not None:fields['prompt_cache_miss_tokens']=prompt-hit
        elif miss is not None:fields['prompt_cache_hit_tokens']=prompt-miss
    if prompt is not None and output is not None:
        if 'total_tokens' in fields and fields['total_tokens']!=prompt+output:raise ValueError('inconsistent token total')
        fields['total_tokens']=prompt+output
    return fields


@dataclass(frozen=True)
class PriceCard:
    model:str
    checked_on:date
    off_peak:dict[str,Decimal]
    peak:dict[str,Decimal]

    @classmethod
    def load(cls,path:Path|None=None):
        path=path or Path(__file__).with_name('deepseek_pricing.json')
        if path.stat().st_size>16384:raise ValueError('price card too large')
        data=json.loads(path.read_text(encoding='utf-8'))
        if data['model']!='deepseek-flash' or data['currency']!='USD' or data['unit_tokens']!=1000000 or data['source']!=PRICE_SOURCE:
            raise ValueError('unsupported price card')
        rates=[]
        for tier in ('off_peak','peak'):
            rate={key:Decimal(data[tier][key]) for key in ('cache_hit','cache_miss','output')}
            if any(not v.is_finite() or not 0<v<=1000 or v.as_tuple().exponent < -6 for v in rate.values()):
                raise ValueError('invalid price')
            if rate['cache_hit']>rate['cache_miss']:raise ValueError('invalid cache price')
            rates.append(rate)
        if any(rates[0][key]>rates[1][key] for key in rates[0]):raise ValueError('invalid peak price')
        return cls(data['model'],date.fromisoformat(data['checked_on']),*rates)


def peak_possible(start:datetime,end:datetime) -> bool:
    # The official weekday peak slots exclude Chinese holidays. Without a
    # verified holiday calendar, a candidate peak is a range, never a fake exact rate.
    if start.tzinfo is None or end.tzinfo is None:return True
    start,end=start.astimezone(timezone.utc),end.astimezone(timezone.utc)
    if not 0<=(end-start).total_seconds()<=120:return True
    points=[start,end]
    day=datetime.combine(start.date(),time(),timezone.utc)
    while day<=end:
        points.extend(day+timedelta(hours=h) for h in (1,4,6,10) if start<=day+timedelta(hours=h)<=end)
        day+=timedelta(days=1)
    return any(p.weekday()<5 and (1<=p.hour<4 or 6<=p.hour<10) for p in points)


class UsageLedger:
    """One record per submitted attempt; memory stays constant for a full course."""
    def __init__(self,model='deepseek-flash',*,price_card=None,provider='deepseek'):
        self.model=model;self.provider=provider;self.card=price_card;self.price_error=False
        if price_card is None and provider=='deepseek':
            try:self.card=PriceCard.load()
            except (OSError,ValueError,KeyError,TypeError,InvalidOperation):self.price_error=True
        self.attempts=self.missing=self.partial=self.invalid=self.priced=self.unpriced=0
        self.low=self.high=Decimal(0);self.usage={};self.notes=set()

    def record(self,value,start:datetime,end:datetime):
        self.attempts+=1
        try:usage=read_usage(value) if value is not None else {}
        except (ValueError,TypeError):usage={};self.invalid+=1
        if not usage:self.missing+=1
        elif not all(k in usage for k in ('prompt_tokens','completion_tokens','total_tokens')):self.partial+=1
        for key,count in usage.items():self.usage[key]=self.usage.get(key,0)+count
        prompt,output=usage.get('prompt_tokens'),usage.get('completion_tokens')
        if not self.card or self.card.model!=self.model or prompt is None or output is None:
            self.unpriced+=1;return
        self.priced+=1
        hit=usage.get('prompt_cache_hit_tokens')
        if hit is None:
            # Missing cache breakdown permits a valid range, not an assumption
            # that every input token was a cache miss (or free).
            low_hit,high_hit=prompt,0;self.notes.add('cache_breakdown_missing')
        else:low_hit=high_hit=hit
        possible=peak_possible(start,end)
        if possible:self.notes.add('peak_or_holiday_uncertain')
        if start.tzinfo is None or end.tzinfo is None or not 0<=(end-start).total_seconds()<=120:self.notes.add('request_clock_uncertain')
        if end.date()<self.card.checked_on or (end.date()-self.card.checked_on).days>30:self.notes.add('price_snapshot_age')
        def cost(rates,cached):
            return (cached*rates['cache_hit']+(prompt-cached)*rates['cache_miss']+output*rates['output'])/1000000
        self.low+=cost(self.card.off_peak,low_hit)
        self.high+=cost(self.card.peak if possible else self.card.off_peak,high_hit)

    def snapshot(self):
        complete=bool(self.attempts) and self.missing==self.partial==0
        cost={'currency':'USD','low':format(self.low,'f') if self.priced else None,
              'high':format(self.high,'f') if self.priced else None,
              'complete':bool(self.attempts) and self.unpriced==0,
              'priced_attempts':self.priced,'unpriced_attempts':self.unpriced,
              'price_checked_on':self.card.checked_on.isoformat() if self.card else None,
              'source':PRICE_SOURCE if self.provider=='deepseek' else None,'notes':sorted(self.notes),
              'pricing_available':self.card is not None and self.card.model==self.model,
              'basis':'official_price_snapshot_estimate_not_bill'}
        return {'usage_revision':self.attempts,'usage_attempts':self.attempts,'token_usage':dict(self.usage),
                'provider':self.provider,'model':self.model,
                'attempts_without_usage':self.missing,'attempts_partial_usage':self.partial,'invalid_usage_attempts':self.invalid,
                'usage_complete':complete,'cost_estimate':cost,
                'cost_usd':cost['low'] if cost['complete'] and cost['low']==cost['high'] else None,
                'cost_note':'estimate only; unreported attempts excluded; platform bill is authoritative'}
