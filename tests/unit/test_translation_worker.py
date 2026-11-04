import asyncio
from dataclasses import replace
import json
import pytest
pytest.importorskip('httpx',reason='install translation extra for M2 worker tests')
from app.subtitles.coordinator import SubtitleCoordinator
from app.subtitles.models import SubtitleState
from app.translation.client import ProviderError,StreamEvent
from app.translation.config import TranslationConfig
from app.translation.glossary import Glossary
from app.translation.worker import TranslationWorker


def setup(client,config=None):
    config=config or replace(TranslationConfig(),retry_delay_seconds=.001,finish_grace_seconds=.5)
    events=[]
    emit=lambda event,**data:events.append((event,data))
    c=SubtitleCoordinator(config,emit,realtime=False)
    w=TranslationWorker(config,client,Glossary([]),c,emit)
    w.start()
    return c,w,events


class Client:
    def __init__(self):self.calls=0;self.closed=False
    async def stream(self,messages):
        self.calls+=1
        yield StreamEvent('delta',text='矩阵不可逆。')
        yield StreamEvent('usage',usage={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15})
        yield StreamEvent('done')
    async def close(self):self.closed=True


def test_normal_completion_and_duplicate_offer_do_not_duplicate_api_or_history():
    async def run():
        client=Client();c,w,events=setup(client);history=[];c.on_final=history.append
        c.submit_text('The matrix is not invertible.','en')
        request=c.request(c.records[1]);w.offer(request)
        stats=await w.close()
        assert c.records[1].state==SubtitleState.FINAL and len(history)==1
        assert stats['translation_attempts']==1 and client.calls==1 and client.closed
        assert stats['token_usage']['total_tokens']==15
    asyncio.run(run())


def test_real_out_of_order_completions_preserve_corresponding_source():
    async def run():
        order=[]
        class OutOfOrder(Client):
            async def stream(self,messages):
                source=json.loads(messages[-1]['content'])['current_source_text']
                await asyncio.sleep(.04 if source=='first' else .001)
                order.append(source)
                yield StreamEvent('delta',text='译文:'+source)
                yield StreamEvent('done')
        c,w,_=setup(OutOfOrder())
        c.submit_text('first','en');c.submit_text('second','en')
        await w.close()
        assert order==['second','first']
        assert c.records[1].translated_text=='译文:first' and c.records[2].translated_text=='译文:second'
        assert all(r.state==SubtitleState.FINAL for r in c.records.values())
    asyncio.run(run())


def test_slow_old_preview_cannot_overwrite_new_final():
    async def run():
        gate=asyncio.Event();started=asyncio.Event()
        class Slow(Client):
            async def stream(self,messages):
                source=json.loads(messages[-1]['content'])['current_source_text']
                if source=='The system is not':
                    started.set();await gate.wait()
                    yield StreamEvent('delta',text='旧译文')
                else:yield StreamEvent('delta',text='系统不稳定。')
                yield StreamEvent('usage',usage={'prompt_tokens':10,'completion_tokens':5,'total_tokens':15})
                yield StreamEvent('done')
        c,w,events=setup(Slow())
        def update(revision,text,offset,endpoint):
            c.consume(session_id=c.session_id,revision=revision,source_language='en',
                confirmed_words=[{'text':s,'start':offset+i*100,'end':offset+(i+1)*100} for i,s in enumerate(text.split())],
                candidate_words=[],endpoint=endpoint,stability_reason='local_agreement')
        update(1,'The system is not',100,False)
        await asyncio.wait_for(started.wait(),.2)
        update(2,'stable.',500,True)
        for _ in range(50):
            if c.records[1].state==SubtitleState.FINAL:break
            await asyncio.sleep(.002)
        assert c.records[1].state==SubtitleState.FINAL
        gate.set();stats=await w.close()
        assert c.records[1].translated_text=='系统不稳定。'
        assert any(event=='translation_discarded' for event,_ in events)
        assert stats['token_usage']['total_tokens']==30 and stats['usage_attempts']==2
    asyncio.run(run())


def test_timeout_retries_are_limited_and_keep_source_visible():
    async def run():
        class Never(Client):
            async def stream(self,messages):
                self.calls+=1
                yield StreamEvent('delta',text='部分')
                await asyncio.Event().wait()
        client=Never()
        config=replace(TranslationConfig(),request_timeout_seconds=.02,connect_timeout_seconds=.01,
                       retry_delay_seconds=.001,max_retries=1,finish_grace_seconds=.4)
        c,w,_=setup(client,config);c.submit_text('Not stable.','en')
        stats=await w.close()
        assert client.calls==2 and stats['translation_retries']==1
        assert c.records[1].source_text=='Not stable.' and c.records[1].state==SubtitleState.PREVIEW
        assert c.records[1].translation_status=='request_deadline'
        assert stats['attempts_without_usage']==2
    asyncio.run(run())


def test_rate_limit_retry_and_usage_from_failed_stream_is_preserved():
    async def run():
        class Retry(Client):
            async def stream(self,messages):
                self.calls+=1
                yield StreamEvent('usage',usage={'total_tokens':7})
                if self.calls==1:raise ProviderError('rate_limited',retryable=True)
                yield StreamEvent('delta',text='成功')
                yield StreamEvent('done')
        c,w,_=setup(Retry());c.submit_text('Stable.','en')
        stats=await w.close()
        assert stats['translation_attempts']==2 and stats['token_usage']['total_tokens']==14
        assert stats['attempts_without_usage']==0 and c.records[1].state==SubtitleState.FINAL
    asyncio.run(run())


def test_auth_error_disables_further_requests_and_does_not_log_secret():
    async def run():
        class Auth(Client):
            async def stream(self,messages):
                self.calls+=1
                raise ProviderError('authentication_failed',fatal=True,status=401)
                yield
        config=replace(TranslationConfig(),concurrency=1,finish_grace_seconds=.3)
        client=Auth();c,w,events=setup(client,config)
        for i in range(5):c.submit_text('source '+str(i),'en')
        stats=await w.close()
        assert client.calls==1 and not c.available
        assert all(r.state==SubtitleState.PREVIEW for r in c.records.values())
        assert all(r.source_text for r in c.records.values()) and stats['translation_retries']==0
    asyncio.run(run())


def test_cancel_closes_stream_and_client_without_finalizing_partial():
    async def run():
        entered=asyncio.Event();closed=[]
        class Streaming(Client):
            async def stream(self,messages):
                try:
                    entered.set();yield StreamEvent('delta',text='部分')
                    await asyncio.Event().wait()
                finally:closed.append(True)
        client=Streaming();c,w,_=setup(client);c.submit_text('source','en')
        await asyncio.wait_for(entered.wait(),.2)
        stats=await w.close(drain=False)
        assert closed and client.closed and c.records[1].state==SubtitleState.PREVIEW
        assert stats['attempts_without_usage']==1 and all(task.done() for task in w.tasks)
    asyncio.run(run())


def test_pending_queue_is_bounded_and_drops_are_visible():
    async def run():
        config=replace(TranslationConfig(),queue_capacity=2,finish_grace_seconds=.5)
        c,w,events=setup(Client(),config)
        for i in range(10):c.submit_text('source '+str(i),'en')
        assert len(w.pending)==2
        stats=await w.close()
        assert stats['translation_backlog_dropped']==8
        assert sum(event=='translation_backlog_drop' for event,_ in events)==8
        assert not c.summary()['translation_complete']
    asyncio.run(run())


def test_expired_job_is_not_sent_and_missing_key_makes_zero_requests():
    async def run():
        client=Client();c,w,_=setup(client)
        c.submit_text('source','en')
        key=next(iter(w.pending));w.pending[key]=replace(w.pending[key],created_ns=0)
        stats=await w.close()
        assert client.calls==0 and stats['translation_expired']==1
        c,w,_=setup(None);c.submit_text('source','en');stats=await w.close()
        assert stats['translation_attempts']==0 and not c.available and not c.summary()['translation_complete']
    asyncio.run(run())
