from __future__ import annotations
import asyncio
from collections import OrderedDict
import uuid
from datetime import datetime,timezone
from app.asr.clock import now_ns
from app.subtitles.models import TranslationRequest
from .client import ProviderError
from .prompt import prepare_messages,PromptBudgetExceeded
from .usage import UsageLedger


class TranslationWorker:
    def __init__(self,config,client,glossary,coordinator,emit,*,clock=now_ns,disabled_reason='missing_api_key',utc_clock=None):
        self.config,self.client,self.glossary,self.coordinator,self.emit=config,client,glossary,coordinator,emit
        self.clock=clock
        self.utc_clock=utc_clock or (lambda:datetime.now(timezone.utc));self.accounting=UsageLedger(config.model,provider=config.provider)
        self.disabled_reason=disabled_reason
        self.pending: OrderedDict[int,TranslationRequest]=OrderedDict()
        self.tasks=[];self.wake=asyncio.Event();self.idle=asyncio.Event();self.idle.set()
        self.active=0;self.stopping=False;self.available=client is not None
        self.requests=self.retries=self.failures=self.expired=self.dropped=self.attempts_without_usage=0
        self.usage={};self.high_water=0
        self.coordinator.submit=self.offer

    def statistics(self):
        return {'pending':len(self.pending),'active':self.active,'capacity':self.config.queue_capacity,
                'oldest_wait_seconds':(self.clock()-min(r.created_ns for r in self.pending.values()))/1e9 if self.pending else 0}

    def start(self):
        self.emit('translation_usage',**self.accounting.snapshot())
        if not self.available:
            self.coordinator.unavailable(self.disabled_reason);return
        self.emit('translation_status',available=True,provider=self.config.provider,model=self.config.model,mode=self.config.mode,
                  thinking='disabled' if self.config.provider=='deepseek' else 'provider_default',streaming=True)
        self.tasks=[asyncio.create_task(self._worker()) for _ in range(self.config.concurrency)]

    def offer(self,request:TranslationRequest):
        if not self.available or self.stopping:
            self.coordinator.fail(request,'translation_unavailable');return
        if not self.coordinator.current_request(request):return
        old=self.pending.pop(request.segment_id,None)
        if old:self.emit('translation_queued_revision_replaced',segment_id=old.segment_id,revision=old.revision)
        if len(self.pending)>=self.config.queue_capacity:
            victim=next((key for key,value in self.pending.items() if not value.source_closed),None)
            if victim is None and not request.source_closed:
                self.dropped+=1
                self.emit('translation_backlog_drop',segment_id=request.segment_id,revision=request.revision,reason='preview_queue_full')
                self.coordinator.fail(request,'preview_queue_full');return
            if victim is None:victim=next(iter(self.pending))
            evicted=self.pending.pop(victim);self.dropped+=1
            self.coordinator.fail(evicted,'translation_backlog_expired')
            self.emit('translation_backlog_drop',segment_id=evicted.segment_id,revision=evicted.revision,reason='bounded_queue')
        self.pending[request.segment_id]=request
        self.high_water=max(self.high_water,len(self.pending));self.idle.clear();self.wake.set()
        self.emit('translation_queue',**self.statistics())

    def _pop(self):
        if not self.pending:return None
        key=next((k for k,v in self.pending.items() if v.source_closed),next(iter(self.pending)))
        return self.pending.pop(key)

    async def _attempt(self,request,attempt,prompt,started,account):
        text='';first=last_emit=0;usage=None;done=False
        async for event in self.client.stream(prompt):
            if event.kind=='usage':usage=event.usage;account['usage']=usage
            elif event.kind=='delta':
                text+=event.text
                now=self.clock()
                if not first and text.strip():
                    first=now
                    account['first_output_ns']=now
                    self.emit('translation_first_output',segment_id=request.segment_id,revision=request.revision,
                              attempt_id=attempt,request_seconds=(now-started)/1e9,
                              current_revision=self.coordinator.current_request(request),
                              audio_end_to_first_seconds=(now-request.audio_end_ns)/1e9 if self.coordinator.realtime else None)
                if first and (not last_emit or now-last_emit>=self.config.stream_emit_interval_seconds*1e9):
                    self.coordinator.partial(request,attempt,text);last_emit=now
            elif event.kind=='done':done=True
        if not done or not text.strip():raise ProviderError('incomplete_translation_stream')
        return text,usage,first

    def _account(self,usage,started):
        self.accounting.record(usage,started,self.utc_clock())
        self.usage=dict(self.accounting.usage);self.attempts_without_usage=self.accounting.missing
        self.emit('translation_usage',**self.accounting.snapshot())

    async def _translate(self,request,dequeued_ns):
        for retry in range(self.config.max_retries+1):
            if not self.available:
                self.coordinator.fail(request,'translation_unavailable');return
            age=(self.clock()-request.created_ns)/1e9
            if age>=self.config.task_ttl_seconds:
                self.expired+=1;self.coordinator.fail(request,'translation_expired')
                self.emit('translation_expired',segment_id=request.segment_id,revision=request.revision);return
            if not self.coordinator.current_request(request):
                self.emit('translation_skipped',segment_id=request.segment_id,revision=request.revision,reason='stale_before_submit');return
            attempt=uuid.uuid4().hex
            preparing=self.clock()
            try:
                prompt,prompt_metrics=prepare_messages(request.source_text,request.source_language,
                    self.coordinator.context(request),self.glossary,self.config)
            except PromptBudgetExceeded as error:
                self.failures+=1;self.coordinator.fail(request,'translation_prompt_too_large')
                self.emit('translation_error',segment_id=request.segment_id,revision=request.revision,
                    code='translation_prompt_too_large',retryable=False,request_not_sent=True,
                    required_prompt_chars=error.required,prompt_char_limit=error.limit,source_chars=len(request.source_text))
                return
            if not self.coordinator.begin(request,attempt):return
            started=self.clock();self.requests+=1
            deadline=min(self.config.request_timeout_seconds,self.config.task_ttl_seconds-age)
            self.emit('translation_submitted',segment_id=request.segment_id,revision=request.revision,
                      attempt_id=attempt,phase='final' if request.source_closed else 'preview',mode=self.config.mode,
                      queue_wait_seconds=(dequeued_ns-request.created_ns)/1e9,
                      preparation_seconds=(started-preparing)/1e9,attempt_age_seconds=(started-request.created_ns)/1e9,
                      attempt_number=retry+1,timeout_seconds=deadline,**prompt_metrics)
            usage=None;account={'usage':None};started_utc=self.utc_clock()
            try:
                try:
                    text,usage,first=await asyncio.wait_for(self._attempt(request,attempt,prompt,started,account),
                        timeout=deadline)
                except ProviderError as error:
                    if account['usage'] is None:account['usage']=error.usage
                    raise
                finally:self._account(account['usage'],started_utc)
                applied=self.coordinator.complete(request,attempt,text)
                now=self.clock()
                self.emit('translation_completed',segment_id=request.segment_id,revision=request.revision,
                          attempt_id=attempt,applied=applied,request_seconds=(now-started)/1e9,
                          audio_end_to_complete_seconds=(now-request.audio_end_ns)/1e9 if self.coordinator.realtime else None,
                          usage=usage,translated_chars=len(text),cost_note='see cumulative translation_usage estimate; not a bill',**prompt_metrics)
                return
            except asyncio.CancelledError:
                self.coordinator.fail(request,'translation_cancelled')
                self.emit('translation_cancelled',segment_id=request.segment_id,revision=request.revision)
                raise
            except (ProviderError,TimeoutError) as error:
                if isinstance(error,TimeoutError):error=ProviderError('request_deadline',retryable=True,timeout_phase='request')
                first_output=account.get('first_output_ns')
                self.emit('translation_error',segment_id=request.segment_id,revision=request.revision,
                          attempt_id=attempt,code=error.code,status=error.status,retryable=error.retryable,
                          attempt_number=retry+1,timeout_phase=error.timeout_phase,
                          request_seconds=(self.clock()-started)/1e9,timeout_seconds=deadline,
                          first_output_received=first_output is not None,
                          first_output_seconds=(first_output-started)/1e9 if first_output is not None else None,
                          **prompt_metrics)
                if error.fatal:
                    self.available=False;self.coordinator.unavailable(error.code)
                    for old in list(self.pending.values()):self.coordinator.fail(old,error.code)
                    self.pending.clear();self.failures+=1;return
                # Surface the source-only fallback immediately, including while
                # a bounded retry is waiting. A later matching attempt can fill it.
                retry_pending=bool(error.retryable and retry<self.config.max_retries and self.coordinator.current_request(request))
                self.coordinator.fail(request,error.code,retry_pending=retry_pending)
                if not retry_pending:
                    self.failures+=1;return
                self.retries+=1
                delay=min(2.,max(error.retry_after,self.config.retry_delay_seconds*(2**retry)))
                self.emit('translation_retry_scheduled',segment_id=request.segment_id,revision=request.revision,delay_seconds=delay)
                await asyncio.sleep(delay)

    async def _worker(self):
        while True:
            request=self._pop()
            if request is None:
                if self.active==0:self.idle.set()
                self.wake.clear();await self.wake.wait();continue
            self.active+=1
            self.emit('translation_queue',**self.statistics())
            try:await self._translate(request,self.clock())
            except asyncio.CancelledError:raise
            except Exception as error:
                self.failures+=1
                self.coordinator.fail(request,'translation_internal_error')
                self.emit('translation_error',segment_id=request.segment_id,revision=request.revision,
                          code='translation_internal_error',exception_type=type(error).__name__)
            finally:
                self.active-=1
                self.emit('translation_queue',**self.statistics())
                if not self.pending and self.active==0:self.idle.set()

    async def close(self,drain:bool=True):
        if drain and self.tasks:
            try:await asyncio.wait_for(self.idle.wait(),self.config.finish_grace_seconds)
            except TimeoutError:self.emit('translation_drain_timeout',pending=len(self.pending),active=self.active)
        self.stopping=True
        for request in self.pending.values():self.coordinator.fail(request,'translation_shutdown')
        self.pending.clear()
        for task in self.tasks:task.cancel()
        results=await asyncio.gather(*self.tasks,return_exceptions=True)
        if self.client:await self.client.close()
        for result in results:
            if isinstance(result,BaseException) and not isinstance(result,asyncio.CancelledError):
                self.failures+=1
                self.emit('translation_worker_shutdown_error',exception_type=type(result).__name__)
        return {'translation_mode':self.config.mode,'translation_attempts':self.requests,'translation_retries':self.retries,
                'translation_failures':self.failures,'translation_expired':self.expired,
                'translation_backlog_dropped':self.dropped,'translation_queue_high_water':self.high_water,
                **self.accounting.snapshot()}
