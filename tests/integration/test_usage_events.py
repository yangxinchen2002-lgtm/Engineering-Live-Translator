import asyncio
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal
import json
import pytest
httpx=pytest.importorskip('httpx')
from app.translation.client import DeepSeekClient
from app.translation.config import TranslationConfig
from app.translation.credentials import Credential
from app.translation.glossary import Glossary
from app.translation.worker import TranslationWorker
from app.subtitles.coordinator import SubtitleCoordinator
from app.diagnostics.runtime import RuntimeMetrics

WHEN=datetime(2026,10,31,tzinfo=timezone.utc)
USAGE={'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100,
       'prompt_cache_hit_tokens':800,'prompt_cache_miss_tokens':200}


def event(value):return ('data: '+json.dumps(value)+'\n\n').encode()


def body(*,finish='stop',done=True,duplicates=False):
    result=event({'choices':[{'delta':{'content':'译文'},'finish_reason':None}]})
    result+=event({'choices':[{'delta':{},'finish_reason':finish}],'usage':USAGE})
    if duplicates:result+=event({'choices':[],'usage':USAGE})
    if done:result+=b'data: [DONE]\n\n'
    return result


@pytest.mark.parametrize('mode',['preview','sentence'])
def test_real_http_parser_worker_metrics_count_each_retry_and_duplicate_usage_once(mode):
    async def run():
        requests=[];snapshots=[];metrics=RuntimeMetrics()
        def handle(request):
            requests.append(json.loads(request.content))
            return httpx.Response(200,headers={'content-type':'text/event-stream'},
                content=body(finish='insufficient_system_resource') if len(requests)==1 else body(duplicates=True))
        config=replace(TranslationConfig(),mode=mode,retry_delay_seconds=.001,finish_grace_seconds=2)
        def emit(name,**data):
            metrics.event({'event':name,**data})
            if name=='translation_usage':snapshots.append(metrics.snapshot())
        client=DeepSeekClient(config,Credential('test-only-no-real-key'),transport=httpx.MockTransport(handle))
        coordinator=SubtitleCoordinator(config,emit,realtime=False)
        worker=TranslationWorker(config,client,Glossary([]),coordinator,emit,utc_clock=lambda:WHEN)
        worker.start();coordinator.submit_text('The system is stable.','en');stats=await worker.close()
        assert len(requests)==2 and all(r['stream_options']=={'include_usage':True} for r in requests)
        assert stats['token_usage']['total_tokens']==2200 and stats['usage_attempts']==2
        assert metrics.snapshot()['reported_token_usage']['total_tokens']==2200
        assert [s['usage_attempts'] for s in snapshots]==[0,1,2]
        assert Decimal(stats['cost_usd'])==Decimal('0.0001848')
        assert stats['attempts_without_usage']==0
    asyncio.run(run())


def test_disconnect_without_usage_is_unknown_live_before_session_ends():
    async def run():
        metrics=RuntimeMetrics();seen=[]
        def emit(name,**data):metrics.event({'event':name,**data});seen.append((name,data))
        config=replace(TranslationConfig(),max_retries=0,finish_grace_seconds=1)
        client=DeepSeekClient(config,Credential('test-only'),transport=httpx.MockTransport(
            lambda r:httpx.Response(200,headers={'content-type':'text/event-stream'},
                content=event({'choices':[{'delta':{'content':'部分'},'finish_reason':None}]}))))
        coordinator=SubtitleCoordinator(config,emit,realtime=False)
        worker=TranslationWorker(config,client,Glossary([]),coordinator,emit,utc_clock=lambda:WHEN)
        worker.start();coordinator.submit_text('Source.','en');stats=await worker.close()
        assert stats['attempts_without_usage']==1 and stats['cost_usd'] is None
        assert metrics.snapshot()['attempts_without_usage']==1 and metrics.snapshot()['usage_pending']==0
        assert len([1 for e,d in seen if e=='translation_usage'])==2
    asyncio.run(run())


@pytest.mark.parametrize('reported',[True,False])
def test_cancellation_preserves_received_usage_and_never_defaults_missing_usage_to_zero(reported):
    async def run():
        entered=asyncio.Event();events=[]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                if reported:yield event({'choices':[],'usage':USAGE})
                entered.set();await asyncio.Event().wait()
        config=replace(TranslationConfig(),finish_grace_seconds=.5)
        client=DeepSeekClient(config,Credential('test-only'),transport=httpx.MockTransport(
            lambda r:httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())))
        emit=lambda name,**data:events.append((name,data))
        coordinator=SubtitleCoordinator(config,emit,realtime=False)
        worker=TranslationWorker(config,client,Glossary([]),coordinator,emit,utc_clock=lambda:WHEN)
        worker.start();coordinator.submit_text('Source.','en');await asyncio.wait_for(entered.wait(),1)
        stats=await worker.close(drain=False)
        assert stats['usage_attempts']==1 and stats['attempts_without_usage']==int(not reported)
        assert stats['token_usage'].get('total_tokens')==(1100 if reported else None)
        assert all(task.done() for task in worker.tasks)
    asyncio.run(run())
