from __future__ import annotations
from collections import OrderedDict
import json


class EventDecoder:
    def __init__(self,limit:int=262144):self.pending=bytearray();self.limit=limit

    def feed(self,data:bytes) -> list[dict]:
        self.pending.extend(data);events=[]
        while (end:=self.pending.find(b'\n'))>=0:
            if end>self.limit:raise ValueError('backend event exceeds size limit')
            raw=bytes(self.pending[:end]);del self.pending[:end+1]
            if not raw.strip():continue
            value=json.loads(raw.decode('utf-8'))
            if not isinstance(value,dict) or not isinstance(value.get('event'),str):raise ValueError('invalid backend event')
            events.append(value)
        if len(self.pending)>self.limit:raise ValueError('incomplete backend event exceeds size limit')
        return events

    def finish(self):
        if self.pending.strip():raise ValueError('backend ended with an incomplete event')


class SubtitleViewModel:
    def __init__(self,capacity=128):
        self.capacity=capacity;self.session=None;self.records=OrderedDict();self.latest=None

    def reset(self):self.session=None;self.records.clear();self.latest=None

    def update(self,value:dict) -> bool:
        if value.get('event')!='subtitle':return False
        required=('session_id','segment_id','revision','candidate_revision','source_text','candidate_text','translated_text','state')
        if not all(key in value for key in required):raise ValueError('incomplete subtitle event')
        for key in ('segment_id','revision','candidate_revision'):
            if type(value[key]) is not int or value[key]<0:raise ValueError('invalid subtitle version/identity')
        if value['state'] not in ('preview','final') or not isinstance(value['session_id'],str):raise ValueError('invalid subtitle state/session')
        if any(not isinstance(value[key],str) or len(value[key])>16384 for key in ('source_text','candidate_text','translated_text')):
            raise ValueError('invalid subtitle text')
        if self.session is None:self.session=value['session_id']
        if self.session!=value['session_id']:return False
        key=value['segment_id'];old=self.records.get(key)
        if old:
            if old['state']=='final':return False
            if value['revision']<old['revision']:return False
            if value['revision']==old['revision'] and value['source_text']!=old['source_text']:return False
            if value['revision']==old['revision'] and value['candidate_revision']<old['candidate_revision']:return False
        self.records[key]=dict(value)
        if self.latest is None or key>self.latest:self.latest=key
        while len(self.records)>self.capacity:self.records.popitem(last=False)
        return True

    @property
    def current(self):return self.records.get(self.latest)

    def recent(self):return sorted(self.records.values(),key=lambda r:r['segment_id'],reverse=True)
