"""Official protocol fixtures exercise real HTTPX/SSE adapters, never live keys."""
import asyncio
from dataclasses import replace
from datetime import datetime,timezone
import json
import pytest
import httpx
from app.translation.config import TranslationConfig
from app.translation.credentials import Credential
from app.translation.providers import PROVIDERS,validate_model
from app.translation.factory import create_client
from app.translation.client import ProviderError
from app.translation.official_client import StreamState,normalize_usage
from app.translation.usage import UsageLedger


def config(provider,**changes):
    info=PROVIDERS[provider]
    return replace(TranslationConfig(),provider=provider,base_url=info.base_url,model=info.models[0],**changes).validate()


def sse(value):return ('data: '+json.dumps(value,ensure_ascii=False)+'\n\n').encode()


def response_bytes(provider,text='矩阵不可逆。'):
    if provider=='deepseek':
        return sse({'choices':[{'delta':{'content':text}}]})+sse({'choices':[{'delta':{},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':20,'completion_tokens':6,'total_tokens':26}})+b'data: [DONE]\n\n'
    if provider=='openai':
        return sse({'type':'response.output_text.delta','output_index':1,'delta':text})+sse({'type':'response.completed','response':{
            'status':'completed','model':'gpt-4.1-mini','usage':{'input_tokens':20,'output_tokens':6,'total_tokens':26,
            'input_tokens_details':{'cached_tokens':5}},'output':[{'type':'reasoning'},{'type':'message'}]}})
    if provider=='claude':
        return sse({'type':'message_start','message':{'model':'claude-haiku-5-5','usage':{
            'input_tokens':12,'cache_read_input_tokens':5,'cache_creation_input_tokens':3,'output_tokens':1}}})+sse({
            'type':'content_block_delta','delta':{'type':'text_delta','text':text}})+sse({'type':'message_delta',
            'delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':6}})+sse({'type':'message_stop'})
    return sse({'candidates':[{'index':0,'content':{'parts':[{'text':'hidden reasoning','thought':True},{'text':text}]},
        'finishReason':'STOP'}]})+sse({'usageMetadata':{'promptTokenCount':20,'candidatesTokenCount':4,
        'thoughtsTokenCount':2,'totalTokenCount':26,'cachedContentTokenCount':5}})


class ByteStream(httpx.AsyncByteStream):
    def __init__(self,raw):self.raw=raw
    async def __aiter__(self):
        for index in range(0,len(self.raw),7):yield self.raw[index:index+7]


@pytest.mark.parametrize('provider',PROVIDERS)
def test_selected_official_endpoint_auth_stream_and_usage(provider):
    async def run():
        seen=[];secret='private-unit-'+provider
        async def handle(request):
            seen.append(request)
            return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=ByteStream(response_bytes(provider)))
        client=create_client(config(provider),Credential(secret,provider=provider),transport=httpx.MockTransport(handle))
        try:events=[row async for row in client.stream([{'role':'system','content':'译为中文。'},{'role':'user','content':'Not invertible.'}])]
        finally:await client.close()
        request=seen[0];body=json.loads(request.content)
        assert secret not in str(request.url) and secret not in request.content.decode()
        assert request.url.host=={'deepseek':'api.deepseek.com','openai':'api.openai.com','claude':'api.anthropic.com',
                                  'gemini':'generativelanguage.googleapis.com'}[provider]
        if provider in ('deepseek','openai'):assert request.headers['authorization']=='Bearer '+secret
        elif provider=='claude':assert request.headers['x-api-key']==secret and request.headers['anthropic-version']=='2023-06-01'
        else:assert request.headers['x-goog-api-key']==secret and request.url.params['alt']=='sse'
        if provider=='deepseek':assert body['thinking']=={'type':'disabled'}
        elif provider=='openai':assert request.url.path=='/v1/responses' and body['store'] is False and body['instructions']=='译为中文。'
        elif provider=='claude':assert request.url.path=='/v1/messages' and body['system']=='译为中文。'
        else:assert request.url.path.endswith(':streamGenerateContent') and body['contents'][0]['parts'][0]['text']=='Not invertible.'
        assert ''.join(row.text for row in events if row.kind=='delta')=='矩阵不可逆。'
        usage=[row.usage for row in events if row.kind=='usage'][-1]
        assert usage['prompt_tokens']==20 and usage['completion_tokens']==6 and usage['total_tokens']==26
        assert events[-1].kind=='done' and client.http.is_closed
    asyncio.run(run())


@pytest.mark.parametrize('provider',['openai','claude','gemini'])
def test_wrong_provider_key_is_rejected_before_http(provider):
    with pytest.raises(ValueError,match='credential'):create_client(config(provider),Credential('private-test-deepseek'))


@pytest.mark.parametrize('provider',PROVIDERS)
@pytest.mark.parametrize('bad',['https://attacker.invalid','https://api.openai.com.evil.invalid/v1','http://api.openai.com/v1'])
def test_provider_host_cannot_be_redirected_to_arbitrary_key_receiver(provider,bad):
    with pytest.raises(ValueError):replace(config(provider),base_url=bad).validate()


@pytest.mark.parametrize('provider',['openai','claude','gemini'])
@pytest.mark.parametrize('status',[401,402,403,429,500,503])
def test_http_failures_preserve_code_and_never_echo_response_or_key(provider,status):
    async def run():
        client=create_client(config(provider),Credential('private-only-test',provider=provider),transport=httpx.MockTransport(
            lambda request:httpx.Response(status,text='private-only-test echoed input')))
        try:
            with pytest.raises(ProviderError) as error:_=[e async for e in client.stream([])]
            assert error.value.status==status and 'private' not in str(error.value)
            assert error.value.retryable==(status in (429,500,503))
        finally:await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('provider',['openai','claude','gemini'])
def test_redirect_is_not_followed_and_midstream_eof_is_not_success(provider):
    async def run():
        calls=[]
        async def redirect(request):calls.append(request.url);return httpx.Response(302,headers={'location':'https://attacker.invalid'})
        client=create_client(config(provider),Credential('private-test-value',provider=provider),transport=httpx.MockTransport(redirect))
        try:
            with pytest.raises(ProviderError):_=[e async for e in client.stream([])]
            assert len(calls)==1
        finally:await client.close()
        raw=response_bytes(provider).split(b'\n\n')[0]+b'\n\n'
        if provider=='gemini':
            first=json.loads(raw.decode()[6:].strip());first['candidates'][0].pop('finishReason');raw=sse(first)
        client=create_client(config(provider),Credential('private-test-value',provider=provider),transport=httpx.MockTransport(
            lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=raw)))
        try:
            with pytest.raises(ProviderError):_=[e async for e in client.stream([])]
        finally:await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('provider',['openai','claude','gemini'])
def test_success_without_usage_is_unknown_cost_not_zero(provider):
    from tests.unit.test_translation_worker import setup
    async def run():
        raw=response_bytes(provider).decode();values=[]
        for block in raw.strip().split('\n\n'):
            value=json.loads(block[6:])
            if provider=='openai':value.get('response',{}).pop('usage',None)
            elif provider=='claude':
                value.pop('usage',None);value.get('message',{}).pop('usage',None)
            else:value.pop('usageMetadata',None)
            values.append(sse(value))
        client=create_client(config(provider),Credential('private-test-value',provider=provider),transport=httpx.MockTransport(
            lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=b''.join(values))))
        c,w,_=setup(client,config(provider));c.submit_text('Not invertible.','en');stats=await w.close()
        assert c.records[1].state=='final' and stats['attempts_without_usage']==1
        assert stats['cost_usd'] is None and not stats['token_usage']
    asyncio.run(run())


@pytest.mark.parametrize('provider',['openai','claude','gemini'])
def test_output_limit_timeout_and_cancellation_are_real_errors(provider):
    async def run():
        client=create_client(config(provider,max_output_chars=128),Credential('private-test-value',provider=provider),transport=httpx.MockTransport(
            lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=response_bytes(provider,'中'*129))))
        try:
            with pytest.raises(ProviderError) as error:_=[e async for e in client.stream([])]
            assert error.value.code=='translation_output_too_large'
        finally:await client.close()
        async def timeout(request):raise httpx.ReadTimeout('private-test-value')
        client=create_client(config(provider),Credential('private-test-value',provider=provider),transport=httpx.MockTransport(timeout))
        try:
            with pytest.raises(ProviderError) as error:_=[e async for e in client.stream([])]
            assert error.value.code=='network_timeout' and error.value.timeout_phase=='read'
        finally:await client.close()
        async def wait(request):await asyncio.Event().wait()
        client=create_client(config(provider),Credential('private-test-value',provider=provider),transport=httpx.MockTransport(wait))
        async def collect():return [e async for e in client.stream([])]
        task=asyncio.create_task(collect());await asyncio.sleep(.001);task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):await task
        finally:await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('provider',['openai','claude','gemini'])
def test_truncated_output_is_never_a_final_success(provider):
    state=StreamState(provider,4096)
    usage={'input_tokens':20,'output_tokens':6,'total_tokens':26}
    if provider=='openai':value={'type':'response.incomplete','response':{'status':'incomplete','usage':usage,'incomplete_details':{'reason':'max_output_tokens'}}}
    elif provider=='claude':
        state.parse(json.dumps({'type':'message_start','message':{'usage':usage}}))
        value={'type':'message_delta','delta':{'stop_reason':'max_tokens'},'usage':{'output_tokens':6}}
    else:value={'candidates':[{'finishReason':'MAX_TOKENS'}],'usageMetadata':{'promptTokenCount':20,'totalTokenCount':26}}
    with pytest.raises(ProviderError) as error:state.parse(json.dumps(value))
    assert error.value.code=='translation_finish_length' and error.value.usage is not None and not state.done


def test_claude_cumulative_usage_is_not_double_counted_and_gemini_thinking_is_included():
    state=StreamState('claude',4096)
    events=[]
    decoder_text=response_bytes('claude').decode()
    for raw in decoder_text.strip().split('\n\n'):events.extend(state.parse(raw[6:]))
    ledger=UsageLedger('claude-haiku-5-5',provider='claude')
    usage=[event.usage for event in events if event.kind=='usage'][-1]
    now=datetime.now(timezone.utc);ledger.record(usage,now,now);result=ledger.snapshot()
    assert result['token_usage']['total_tokens']==26 and result['usage_attempts']==1
    assert result['cost_usd'] is None and not result['cost_estimate']['pricing_available']
    assert normalize_usage('gemini',{'promptTokenCount':20,'totalTokenCount':27,'candidatesTokenCount':3,'thoughtsTokenCount':4})['completion_tokens']==7


def test_unpriced_provider_ui_shows_tokens_and_does_not_imply_free_usage():
    from app.ui.usage import usage_text
    from app.diagnostics.runtime import RuntimeMetrics
    ledger=UsageLedger('gpt-4.1-mini',provider='openai');now=datetime.now(timezone.utc)
    ledger.record({'prompt_tokens':20,'completion_tokens':6,'total_tokens':26},now,now)
    metrics=RuntimeMetrics();metrics.event({'event':'translation_usage',**ledger.snapshot()})
    short,details=usage_text(metrics.snapshot())
    assert '26' in short and '费用未估算' in short and '$0.' not in short
    assert '对应平台账单' in details and '开始中文翻译后' not in details


@pytest.mark.parametrize('provider',['openai','claude','gemini'])
def test_real_adapter_worker_and_coordinator_complete_selected_provider(provider):
    from app.subtitles.coordinator import SubtitleCoordinator
    from app.translation.worker import TranslationWorker
    from app.translation.glossary import Glossary
    async def run():
        cfg=config(provider);events=[];emit=lambda name,**data:events.append((name,data))
        client=create_client(cfg,Credential('private-only-test',provider=provider),transport=httpx.MockTransport(
            lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=response_bytes(provider))))
        coordinator=SubtitleCoordinator(cfg,emit,realtime=False)
        worker=TranslationWorker(cfg,client,Glossary([]),coordinator,emit);worker.start();coordinator.submit_text('The matrix is not invertible.','en')
        stats=await worker.close()
        assert coordinator.records[1].state=='final' and coordinator.records[1].translated_text=='矩阵不可逆。'
        assert stats['token_usage']['total_tokens']==26 and stats['translation_attempts']==1
        assert stats['cost_usd'] is None
        assert next(data for name,data in events if name=='translation_status')['provider']==provider
    asyncio.run(run())


@pytest.mark.parametrize('provider,value',[
    ('openai',[]),('openai',{'type':'response.completed','response':[]}),
    ('openai',{'type':'response.output_text.delta','delta':{'text':'invalid'}}),
    ('openai',{'type':'response.completed','response':{'status':'completed','usage':[]}}),
    ('claude',[]),('claude',{'type':'message_start','message':[]}),
    ('claude',{'type':'content_block_delta','delta':[]}),('claude',{'type':'content_block_start','content_block':[]}),
    ('gemini',[]),('gemini',{'candidates':[None]}),('gemini',{'candidates':{}}),
    ('gemini',{'candidates':[{'content':{'parts':[None]}}]})])
def test_malformed_stream_shapes_fail_safely(provider,value):
    state=StreamState(provider,4096)
    with pytest.raises(ProviderError):state.parse(json.dumps(value))
