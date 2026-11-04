from __future__ import annotations
from collections import OrderedDict
from dataclasses import asdict,replace
import re
import uuid
from app.asr.clock import now_ns,latency_seconds
from app.translation.config import TranslationConfig
from app.translation.context import bounded_context,context_chars
from .models import SourceWord,Subtitle,SubtitleState,TranslationRequest
from app.languages import SOURCE_LANGUAGES, NO_SPACE_LANGUAGES, join_source

ABBREVIATIONS = {'z.b.','d.h.','u.a.','bzw.','ca.','dr.','prof.','e.g.','i.e.','etc.','vs.','fig.','eq.'}
LANGUAGE_ABBREVIATIONS = {'fr': {'m.','mme.','mlle.','p.ex.','c.-à-d.','env.'},
    'it': {'dott.','dott.ssa.','ecc.','p.es.','ing.'},
    'ru': {'т.е.','т.д.','т.п.','др.','рис.','им.','г.'}}


def sentence_end(text:str,language:str) -> bool:
    word = text.strip().rstrip('"\'”’)]}」』）】')
    if (word.casefold() in ABBREVIATIONS | LANGUAGE_ABBREVIATIONS.get(language,set())
            or re.fullmatch(r'[^\W\d_]\.',word)): return False
    if language=='de' and re.fullmatch(r'\d+\.',word): return False
    return bool(re.search(r'[.!?。！？]$',word))


class SubtitleCoordinator:
    def __init__(self,config:TranslationConfig,emit,*,session_id:str|None=None,realtime:bool=True,clock=now_ns):
        self.config,self.emit,self.realtime,self.clock = config,emit,realtime,clock
        self.session_id = session_id or uuid.uuid4().hex
        self.records: OrderedDict[int,Subtitle] = OrderedDict()
        self.current: int|None = None
        self.next_id = self.last_asr_revision = 0
        self.stable_cursor = 0
        self.word_count = 0
        self.last_preview: dict[int,int] = {}
        self.last_submitted: dict[int,int] = {}
        self.first_available: set[int] = set()
        self.submit = lambda request: None
        self.on_final = lambda record: None
        self.on_source_closed = lambda record: None
        self.final_context: list[Subtitle] = []
        self.available = True
        self.final_count = self.unavailable_count = self.discarded = 0
        self.evicted_untranslated = 0

    def _publish(self,record:Subtitle) -> None:
        self.emit('subtitle',**asdict(record))

    def _new(self,language:str,start:int,end:int) -> Subtitle:
        while len(self.records)>=self.config.record_capacity:
            key,old = next(iter(self.records.items()))
            if key==self.current: raise BufferError('cannot evict active source subtitle')
            self.records.pop(key);self.last_preview.pop(key,None);self.last_submitted.pop(key,None);self.first_available.discard(key)
            if old.source_text and old.state!=SubtitleState.FINAL:self.evicted_untranslated+=1
            self.emit('subtitle_evicted',segment_id=key,state=old.state,reason='bounded_display_history')
        self.next_id+=1
        record=Subtitle(self.session_id,self.next_id,0,language,'','',start,end,
                        translation_status='waiting_sentence' if self.config.mode=='sentence' and self.available else 'waiting')
        self.records[record.segment_id]=record;self.current=record.segment_id;self.word_count=0
        return record

    def _put(self,record:Subtitle) -> None:
        previous=self.records.get(record.segment_id)
        if previous and previous.state==SubtitleState.FINAL and previous!=record:
            raise ValueError('locked subtitle is immutable')
        self.records[record.segment_id]=record
        self._publish(record)

    def request(self,record:Subtitle) -> TranslationRequest:
        return TranslationRequest(record.session_id,record.segment_id,record.revision,record.source_language,
                                  record.source_text,record.source_closed,record.start_sample,record.end_sample,
                                  record.audio_end_ns,self.clock())

    def _offer(self,record:Subtitle) -> None:
        if not record.source_text: return
        if self.last_submitted.get(record.segment_id)==record.revision:return
        if not self.available:
            self.fail(self.request(record),'translation_unavailable')
            return
        now=self.clock()
        if not record.source_closed:
            if self.config.mode=='sentence':return
            if self.word_count<self.config.preview_min_words: return
            if now-self.last_preview.get(record.segment_id,-10**20)<self.config.preview_interval_seconds*1e9:return
            self.last_preview[record.segment_id]=now
        self.last_submitted[record.segment_id]=record.revision
        self.submit(self.request(record))

    def _close(self,reason:str) -> None:
        if self.current is None:return
        record=self.records[self.current]
        if record.source_text:
            record=replace(record,revision=record.revision+1,source_closed=True,candidate_text='',
                           close_reason=reason,active_attempt='',completed_attempt='',translation_status='pending',translation_retry_pending=False)
            self._put(record);self.on_source_closed(record);self._offer(record)
        else:
            self.records.pop(record.segment_id)
            self.emit('subtitle_candidate_discarded',segment_id=record.segment_id,reason='no_confirmed_source')
        self.current=None;self.word_count=0

    def consume(self,*,session_id:str,revision:int,source_language:str,confirmed_words:list[dict],
                candidate_words:list[dict],endpoint:bool,stability_reason:str,**ignored) -> None:
        if session_id!=self.session_id:raise ValueError('ASR update belongs to another session')
        if revision<=self.last_asr_revision:
            self.emit('asr_update_discarded',revision=revision,reason='duplicate_or_old');return
        self.last_asr_revision=revision
        if source_language not in SOURCE_LANGUAGES:
            self.emit('subtitle_language_unsupported',language=source_language);return
        for item in confirmed_words:
            word=SourceWord(**item)
            if (word.start<0 or word.end<word.start or not word.text.strip()
                    or len(word.text.strip())>self.config.max_source_chars):raise ValueError('invalid confirmed source word')
            if word.end<=self.stable_cursor:
                self.emit('subtitle_word_discarded',start_sample=word.start,end_sample=word.end,reason='already_committed');continue
            record=self.records[self.current] if self.current else self._new(source_language,word.start,word.end)
            if record.source_language!=source_language and record.source_text:
                self._close('language_change');record=self._new(source_language,word.start,word.end)
            text=join_source((record.source_text,word.text),source_language)
            if record.source_text and len(text)>self.config.max_source_chars:
                self._close('bounded_phrase');record=self._new(source_language,word.start,word.end)
                text=join_source((word.text,),source_language)
            self.word_count+=1
            self.stable_cursor=word.end
            record=replace(record,revision=record.revision+1,source_language=source_language,source_text=text,
                           candidate_text='',end_sample=word.end,audio_end_ns=word.end_ns,
                           asr_stability=stability_reason,active_attempt='',completed_attempt='',translation_retry_pending=False,
                           translation_status=('waiting_sentence' if self.config.mode=='sentence' and self.available else
                                               'partial' if record.translated_text else 'pending'))
            # Preserve an already displayed prefix, with its own source/revision;
            # late responses still cannot write to this newer canonical revision.
            self.records[record.segment_id]=record
            if sentence_end(word.text,source_language): self._close('sentence_end')
            # Chinese/Japanese alignment pieces are not words. Character bounds and
            # VAD endpoints still close long phrases without splitting at 40 pieces.
            elif source_language not in NO_SPACE_LANGUAGES and self.word_count>=self.config.max_source_words:self._close('bounded_phrase')
        candidate=[SourceWord(**w) for w in candidate_words]
        if candidate or self.current:
            record=self.records[self.current] if self.current else self._new(source_language,candidate[0].start,candidate[-1].end)
            record=replace(record,candidate_text=join_source((w.text for w in candidate),source_language,strip=False),
                           candidate_revision=record.candidate_revision+1)
            self._put(record)
        if endpoint:self._close('asr_endpoint')
        elif self.current:self._offer(self.records[self.current])

    def end_source(self) -> None:
        self._close('input_finished')

    def submit_text(self,text:str,language:str) -> int:
        if language not in SOURCE_LANGUAGES or not text.strip() or len(text)>self.config.max_source_chars:
            raise ValueError('invalid manual text source')
        if self.current is not None:self._close('manual_text_boundary')
        record=self._new(language,0,0)
        record=replace(record,revision=1,source_text=text.strip(),source_closed=True,
                       close_reason='manual_text',asr_stability='not_applicable',translation_status='pending')
        self._put(record);self.on_source_closed(record);self._offer(record);self.current=None
        return record.segment_id

    def current_request(self,request:TranslationRequest) -> bool:
        record=self.records.get(request.segment_id)
        return bool(record and request.session_id==self.session_id and record.state!=SubtitleState.FINAL
                    and request.revision==record.revision and request.source_text==record.source_text
                    and request.source_closed==record.source_closed)

    def _discard(self,request:TranslationRequest,reason:str) -> bool:
        self.discarded+=1
        self.emit('translation_discarded',segment_id=request.segment_id,revision=request.revision,reason=reason)
        return False

    def begin(self,request:TranslationRequest,attempt:str) -> bool:
        if not self.current_request(request):return self._discard(request,'stale_before_attempt')
        record=self.records[request.segment_id]
        if record.completed_attempt:return self._discard(request,'already_completed_revision')
        preserve=bool(record.translation_source_text and request.source_text.startswith(record.translation_source_text))
        self._put(replace(record,active_attempt=attempt,completed_attempt='',translation_status='streaming',translation_retry_pending=False,
                          translated_text=record.translated_text if preserve else '',
                          translated_revision=record.translated_revision if preserve else 0,
                          translation_source_text=record.translation_source_text if preserve else ''))
        return True

    def _available(self,request:TranslationRequest,text:str) -> None:
        if not text.strip() or request.segment_id in self.first_available:return
        self.first_available.add(request.segment_id)
        now=self.clock()
        self.emit('subtitle_translation_first_available',segment_id=request.segment_id,revision=request.revision,
                  available_ns=now,audio_end_ns=request.audio_end_ns,
                  audio_end_to_available_seconds=latency_seconds(request.audio_end_ns,now)
                    if self.realtime and request.audio_end_ns>0 else None,
                  measurement='coordinator state published; not GUI render completion')

    def partial(self,request:TranslationRequest,attempt:str,text:str) -> bool:
        record=self.records.get(request.segment_id)
        if not self.current_request(request) or not record or record.active_attempt!=attempt or record.completed_attempt:
            return self._discard(request,'stale_partial')
        self._put(replace(record,translated_text=text,translated_revision=request.revision,
                          translation_source_text=request.source_text,translation_status='streaming'))
        self._available(request,text)
        return True

    def complete(self,request:TranslationRequest,attempt:str,text:str) -> bool:
        record=self.records.get(request.segment_id)
        if not self.current_request(request) or not record or record.active_attempt!=attempt or record.completed_attempt:
            return self._discard(request,'stale_or_duplicate_complete')
        if not text.strip():raise ValueError('empty translation cannot complete')
        record=replace(record,translated_text=text,translation_source_text=request.source_text,
                       translated_revision=request.revision,completed_attempt=attempt,translation_status='ready',translation_retry_pending=False,
                       state=SubtitleState.FINAL if request.source_closed else SubtitleState.PREVIEW)
        self._put(record)
        self._available(request,text)
        if record.state==SubtitleState.FINAL:
            self.final_count+=1
            candidates=sorted(self.final_context+[record],key=lambda r:(r.end_sample,r.segment_id))
            pairs=[{'source_text':r.source_text,'translated_text':r.translated_text} for r in candidates]
            retained=bounded_context(pairs,self.config.context_count,self.config.context_chars)
            self.final_context=candidates[-len(retained):] if retained else []
            if len(retained)<len(candidates):
                self.emit('translation_context_pruned',removed_entries=len(candidates)-len(retained),
                          retained_entries=len(retained),context_chars=context_chars(retained),
                          context_char_limit=self.config.context_chars,reason='oldest_first_count_and_length')
            self.on_final(record)
        return True

    def fail(self,request:TranslationRequest,reason:str,*,retry_pending:bool=False) -> None:
        if not self.current_request(request):return
        record=self.records[request.segment_id]
        self.unavailable_count+=1
        self._put(replace(record,translation_status=reason,active_attempt='',translation_retry_pending=retry_pending))

    def context(self,request:TranslationRequest) -> list[dict]:
        return [{'source_text':r.source_text,'translated_text':r.translated_text} for r in self.final_context
                if r.session_id==request.session_id and r.segment_id<request.segment_id and r.end_sample<=request.start_sample]

    def unavailable(self,reason:str) -> None:
        self.available=False
        self.emit('translation_unavailable',reason=reason,source_continues=True)
        for record in list(self.records.values()):
            if record.state!=SubtitleState.FINAL and record.source_text:self.fail(self.request(record),reason)

    def summary(self) -> dict:
        pending=sum(bool(r.source_text) and r.state!=SubtitleState.FINAL for r in self.records.values())
        return {'final_subtitles':self.final_count,'untranslated_subtitles':pending+self.evicted_untranslated,
                'discarded_responses':self.discarded,
                'translation_complete':self.final_count>0 and pending==0 and self.evicted_untranslated==0}
