"""Bounded QPC measurements. Core availability, HTTP, and Qt paint stay distinct."""
from collections import OrderedDict,deque
import math


def summary(values):
    ordered=sorted(values)
    if not ordered:return {'count':0,'p50':None,'p95':None,'last':None}
    def percentile(p):
        index=(len(ordered)-1)*p;low=int(index);high=min(low+1,len(ordered)-1)
        return ordered[low]+(ordered[high]-ordered[low])*(index-low)
    return {'count':len(ordered),'p50':percentile(.5),'p95':percentile(.95),'last':values[-1]}


class RuntimeMetrics:
    def __init__(self,capacity=512):
        if not 1<=capacity<=4096:raise ValueError('invalid metric capacity')
        self.capacity=capacity;self.series={};self.latest={};self.counts={};self.usage={}
        self.first_translations=OrderedDict();self.painted_translations=OrderedDict();self.pending=OrderedDict()
        self.invalid=0;self.realtime=True;self.unknown_usage=None
        self.usage_revision=None;self.usage_attempts=0;self.partial_usage=0;self.usage_submitted=0
        self.usage_finished=False;self.cost_estimate=None

    def _accounting(self,row):
        revision=row.get('usage_revision')
        if type(revision) is not int or revision<0 or self.usage_revision is not None and revision<=self.usage_revision:return
        self.usage_revision=revision;self.usage_attempts=revision
        self.usage={k:v for k,v in row.get('token_usage',{}).items() if type(v) is int and v>=0}
        self.unknown_usage=row.get('attempts_without_usage',0);self.partial_usage=row.get('attempts_partial_usage',0)
        self.cost_estimate=dict(row['cost_estimate']) if isinstance(row.get('cost_estimate'),dict) else None

    def finish_usage(self):
        self.usage_finished=True

    def add(self,name,value):
        if value is None:return
        if type(value) not in (int,float) or not math.isfinite(value) or value<0:self.invalid+=1;return
        self.series.setdefault(name,deque(maxlen=self.capacity)).append(value)

    def event(self,row):
        name=row['event']
        if name=='asr_session':self.realtime=row.get('realtime',True)
        elif name=='asr_result':
            self.add('inference',row.get('inference_seconds'));self.add('asr_queue_wait',row.get('queue_wait_seconds'))
        elif name=='transcript':
            if row.get('first_preview_for_segment'):self.add('source_first_available',row.get('latency_seconds'))
            if row.get('state') in ('stable','committed'):self.add('source_stable',row.get('latency_seconds'))
        elif name=='subtitle_translation_first_available':
            self.add('translation_first_available',row.get('audio_end_to_available_seconds'))
            self.first_translations[row['segment_id']]={k:row.get(k) for k in ('revision','audio_end_ns')}
            while len(self.first_translations)>128:self.first_translations.popitem(last=False)
        elif name=='translation_submitted':
            self.add('translation_queue_wait',row.get('queue_wait_seconds'));self.usage_submitted+=1
            self.latest['translation_prompt']={key:row[key] for key in ('source_chars','context_entries','context_chars',
                'context_entries_dropped','glossary_entries','glossary_chars','glossary_entries_dropped',
                'prompt_chars','prompt_utf8_bytes','prompt_char_limit','timeout_seconds') if key in row}
        elif name=='translation_usage':self._accounting(row)
        elif name=='translation_completed':
            self.add('translation_request',row.get('request_seconds'))
            if self.usage_revision is None:
                for key,value in (row.get('usage') or {}).items():
                    if type(value) is int and value>=0:self.usage[key]=self.usage.get(key,0)+value
        elif name=='bilingual_summary':
            if 'usage_revision' in row:self._accounting(row)
            else:
                self.usage={k:v for k,v in row.get('token_usage',{}).items() if type(v) is int and v>=0}
                self.unknown_usage=row.get('attempts_without_usage')
        elif name in ('gpu','asr_queues','translation_queue'):
            self.latest[name]={k:v for k,v in row.items() if k not in ('event','monotonic_ns')
                and type(v) in (int,float,bool) and math.isfinite(v) and v>=0}
        if name in ('preview_window_skipped','asr_final_dropped','translation_backlog_drop','translation_expired',
                    'translation_discarded','translation_error','asr_timeout','bilingual_source_error'):
            self.counts[name]=self.counts.get(name,0)+1

    def begin_paint(self,token,view,record,received_ns,parts=('source','translation')):
        self.pending[(token,view)]={'parts':set(),'received_ns':received_ns,'segment_id':record['segment_id'],
            'expected_parts':set(parts),
            'revision':record['revision'],'translated_revision':record.get('translated_revision',0),
            'has_translation':bool(record.get('translated_text'))}
        while len(self.pending)>8:self.pending.popitem(last=False)

    def painted(self,token,view,part,painted_ns):
        pending=self.pending.get((token,view))
        if not pending:return None
        if part not in pending['expected_parts']:return None
        pending['parts'].add(part)
        if pending['parts']!=pending['expected_parts']:return None
        self.pending.pop((token,view))
        delta=(painted_ns-pending['received_ns'])/1e9
        self.add('ui_delivery_'+view,delta)
        result={'event':'gui_text_painted','view':view,'generation':token,'segment_id':pending['segment_id'],
            'revision':pending['revision'],'received_ns':pending['received_ns'],'painted_ns':painted_ns,
            'delivery_seconds':delta,'valid_delivery':delta>=0,'measurement':'Qt text paint finished; not compositor presentation'}
        key=(pending['segment_id'],view);reference=self.first_translations.get(pending['segment_id'])
        if pending['has_translation'] and key not in self.painted_translations:
            self.painted_translations[key]=True
            while len(self.painted_translations)>256:self.painted_translations.popitem(last=False)
            if (self.realtime and reference and pending['translated_revision']==reference['revision']
                    and type(reference['audio_end_ns']) is int and reference['audio_end_ns']>0):
                latency=(painted_ns-reference['audio_end_ns'])/1e9
                self.add('translation_first_paint_'+view,latency);result['translation_first_paint_seconds']=latency
            else:self.counts['unmatched_translation_paint']=self.counts.get('unmatched_translation_paint',0)+1
        return result

    def snapshot(self):
        unsettled=max(0,self.usage_submitted-self.usage_attempts)
        lost=unsettled if self.usage_finished else 0
        cost=dict(self.cost_estimate) if self.cost_estimate else None
        if cost and lost:cost['complete']=False
        exact=cost.get('low') if cost and cost.get('complete') and cost.get('low')==cost.get('high') else None
        return {'sample_capacity_per_metric':self.capacity,'metrics_seconds':{k:summary(v) for k,v in self.series.items()},
            'latest':self.latest,'events':self.counts,'reported_token_usage':dict(self.usage),
            'attempts_without_usage':(self.unknown_usage or 0)+lost if self.unknown_usage is not None or lost else None,
            'usage_attempts':self.usage_attempts,'attempts_partial_usage':self.partial_usage,
            'usage_pending':0 if self.usage_finished else unsettled,'usage_lost_on_exit':lost,
            'cost_estimate':cost,'invalid_measurements':self.invalid,'cost_usd':exact,'clock':'perf_counter_ns / QPC',
            'note':'bounded rolling samples; core availability and Qt painting are separate; cost is an estimate, not a bill'}
