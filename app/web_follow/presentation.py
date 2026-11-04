"""Bounded media-clock presentation and cumulative reported usage for the desktop."""
from collections import OrderedDict
from decimal import Decimal


class UsageTotals:
    def __init__(self):
        self.pid=None;self.last={};self.tokens={};self.attempts=0;self.missing=0;self.partial=0
        self.low=Decimal(0);self.high=Decimal(0);self.priced=False;self.complete=True;self.revision=0

    def _cost(self,value):
        cost=value.get('cost_estimate') or {}
        try:
            low=Decimal(cost['low']);high=Decimal(cost['high'])
            if not low.is_finite() or not high.is_finite() or low<0 or high<low:raise ValueError()
            return low,high
        except (KeyError,TypeError,ValueError,ArithmeticError):return None

    def _fold(self,value):
        for key,n in value.get('token_usage',{}).items():self.tokens[key]=self.tokens.get(key,0)+n
        self.attempts+=value.get('usage_attempts',0);self.missing+=value.get('attempts_without_usage',0)
        self.partial+=value.get('attempts_partial_usage',0)
        if value.get('usage_attempts',0):
            pair=self._cost(value)
            if pair:self.low+=pair[0];self.high+=pair[1];self.priced=True
            else:self.complete=False
            self.complete &= bool((value.get('cost_estimate') or {}).get('complete'))

    def update(self,pid,metrics):
        value=metrics.get('usage')
        if not isinstance(value,dict):return None
        if pid is None:pid=self.pid
        if self.pid!=pid:
            previous=metrics.get('previous_worker_usage')
            if isinstance(previous,dict) and previous.get('usage_revision',0)>=self.last.get('usage_revision',0):self.last=previous
            self._fold(self.last);self.last={};self.pid=pid
        if value==self.last:return None
        self.last=dict(value);self.revision=self.attempts+value.get('usage_revision',0)
        tokens=dict(self.tokens)
        for key,n in value.get('token_usage',{}).items():tokens[key]=tokens.get(key,0)+n
        cost=dict(value.get('cost_estimate') or {});pair=self._cost(value)
        if pair:
            cost.update(low=str(self.low+pair[0]),high=str(self.high+pair[1]),complete=self.complete and bool(cost.get('complete')))
        elif self.priced:
            cost.update(low=str(self.low),high=str(self.high),complete=False)
        return dict(event='translation_usage',usage_revision=self.revision,
                    usage_attempts=self.attempts+value.get('usage_attempts',0),token_usage=tokens,
                    attempts_without_usage=self.missing+value.get('attempts_without_usage',0),
                    attempts_partial_usage=self.partial+value.get('attempts_partial_usage',0),cost_estimate=cost)


class Presentation:
    def __init__(self,session_id,options):
        self.session=session_id;self.options=options;self.entries=OrderedDict();self.next_id=0
        self.loaded_pid=None;self.source_session=None;self.source_generation=None;self.usage=UsageTotals();self.incomplete=False

    def records(self,state):
        current=None;preview='';events=[];position=state['position'];generation=state['generation']
        for cue in state['cues']:
            if cue['start']>position:continue  # Never reveal future prepared sentences.
            if not cue.get('asr_confirmed',True):
                if cue['start']<=position<cue['end']:preview=cue['source']
                continue  # Tentative right-context text is not a transcript/history row.
            key=(state['session_id'],generation,cue['id'])
            old=self.entries.get(key)
            if old is None:self.next_id+=1
            source=cue['source'];translated=cue.get('translation','')
            closed=cue.get('boundary')!='pending'
            revision=(old['revision']+(source!=old['source_text'])) if old else 1
            language=cue.get('source_language') or state.get('metrics',{}).get('language') or self.options['language']
            record=dict(event='subtitle',session_id=self.session,segment_id=old['segment_id'] if old else self.next_id,
                        revision=revision,candidate_revision=0,source_text=source,candidate_text='',translated_text=translated,
                        translated_revision=revision if translated else None,source_closed=closed,
                        source_language=language,state='final' if closed and translated else 'preview',
                        translation_status='ready' if translated else 'unavailable' if cue.get('translation_error') else
                                           'pending' if self.options['translate'] else 'disabled',
                        start_sample=round(cue['start']*16000),end_sample=round(cue['end']*16000))
            if not old or (old.get('state')!='final' and record!=old):
                self.entries[key]=record;events.append(record)
            elif old:record=old
            if cue['start']<=position<cue['end']:current=record['segment_id']
        while len(self.entries)>512:self.entries.popitem(last=False)
        return events,current,preview

    def update(self,state):
        events=[];metrics=state.get('metrics',{});pid=state.get('worker_pid')
        if state['has_source'] and state['session_id']!=self.source_session:
            if self.source_session is not None:self.incomplete=True
            if state.get('start_position',0)>.3:self.incomplete=True
            self.source_session=state['session_id'];events.append({'event':'audio_source_ready','source':'web'})
        if state['has_source']:
            identity=(state['session_id'],state['generation'])
            if self.source_generation is not None and identity!=self.source_generation:self.incomplete=True
            self.source_generation=identity
        if pid and metrics.get('device') and self.loaded_pid!=pid:
            self.loaded_pid=pid;events.append({'event':'asr_model_ready','device':metrics['device']})
        rows,current,preview=self.records(state);events.extend(rows)
        identity=(state['session_id'],pid,metrics.get('worker_restarts',0)) if pid else None
        usage=self.usage.update(identity,metrics)
        if usage:events.append(usage)
        if metrics.get('source_complete') is False:self.incomplete=True
        events.append(dict(event='web_clock',status=state['status'],paired=bool(state.get('paired')),
            has_source=state['has_source'],segment_id=current,position=state['position'],prepared_until=state['prepared_until'],
            paused=state['paused'],rate=state['playback_rate'],worker_pid=pid,worker_busy=state['worker_busy'],
            source_preparation_seconds=metrics.get('source_preparation_seconds'),
            translation_ahead_seconds=state.get('translation_ahead_seconds',0),
            translation_queue=metrics.get('translation_queue',0),translation_last_seconds=metrics.get('translation_last_seconds'),
            translation_overflow=metrics.get('translation_overflow',0),translation_expired=metrics.get('translation_expired',0),
            timestamp_repair_samples=metrics.get('timestamp_repair_samples',0),timestamp_repair_windows=metrics.get('timestamp_repair_windows',0),
            media_timing={k:state.get('metadata',{}).get(k) for k in
                ('container_start_seconds','audio_start_seconds','hls')},
            audio_alignment=metrics.get('audio_alignment',{}),
            clock_offset_seconds=state.get('clock_offset_seconds',0),clock_calibrated=state.get('clock_calibrated',False),
            source_position=state.get('source_position',state['position']),source_prepared_until=state.get('source_prepared_until',state['prepared_until']),
            playback_options=state.get('playback',{}),playback_diagnostics=metrics.get('playback',{}),source_kind=state.get('source_kind','web'),
            skipped_windows=metrics.get('expired_windows_skipped',0),
            error=state.get('error',''),preview_source=preview,device=metrics.get('device'),source_incomplete=self.incomplete,
            tts=metrics.get('tts',{})))
        return events
