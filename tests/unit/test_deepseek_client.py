import asyncio
import json
from dataclasses import replace
import pytest
httpx=pytest.importorskip('httpx',reason='install translation extra for M2 transport tests')
from app.translation.client import DeepSeekClient,ProviderError,SSEDecoder,http_error
from app.translation.config import TranslationConfig
from app.translation.credentials import Credential


def event(value):return ('data: '+json.dumps(value,ensure_ascii=False)+'\r\n\r\n').encode('utf-8')


def chunk(text='',finish=None,usage=None,**delta):
    return {'model':'deepseek-flash','choices':[{'index':0,'delta':{'content':text,**delta},'finish_reason':finish}],
            'usage':usage}


def test_sse_arbitrary_utf8_boundaries_multiline_comments_and_limits():
    raw=b': keepalive\r\n\r\n'+event(chunk('特征值 λ'))+b'data: [DONE]\n\n'
    decoder=SSEDecoder();values=[]
    for byte in raw:values.extend(decoder.feed(bytes([byte])))
    assert json.loads(values[0])['choices'][0]['delta']['content']=='特征值 λ' and values[-1]=='[DONE]'
    assert SSEDecoder().feed(b'data: a\ndata: b\n\n')==['a\nb']
    with pytest.raises(ProviderError):SSEDecoder(limit=4).feed(b'data: too long')
    with pytest.raises(ProviderError):SSEDecoder().feed(b'\xff')


def test_real_request_body_and_usage_on_final_content_chunk():
    async def run():
        seen=[]
        async def handle(request):
            seen.append(json.loads(request.content))
            body=event(chunk('特征值。'))+event(chunk(finish='stop',usage={'prompt_tokens':12,'completion_tokens':4,'total_tokens':16}))+b'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=body)
        client=DeepSeekClient(TranslationConfig(),Credential('private-test-sentinel'),transport=httpx.MockTransport(handle))
        try:events=[e async for e in client.stream([{'role':'user','content':'λ < 0'}])]
        finally:await client.close()
        assert seen[0]['thinking']=={'type':'disabled'} and seen[0]['stream'] is True
        assert seen[0]['stream_options']=={'include_usage':True} and seen[0]['model']=='deepseek-flash'
        assert all('audio' not in k and 'file' not in k for k in seen[0])
        assert events[-1].kind=='done' and next(e.usage for e in events if e.kind=='usage')['total_tokens']==16
    asyncio.run(run())


def test_stream_delivers_first_delta_before_response_finishes_and_closes_on_cancel():
    async def run():
        gate=asyncio.Event();closed=[]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield event(chunk('第一'))
                await gate.wait()
                yield event(chunk('段'))+event(chunk(finish='stop'))+b'data: [DONE]\n\n'
            async def aclose(self):closed.append(True)
        async def handle(request):return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Stream())
        client=DeepSeekClient(TranslationConfig(),Credential('private-test-sentinel'),transport=httpx.MockTransport(handle))
        generator=client.stream([])
        first=await asyncio.wait_for(anext(generator),.3)
        assert first.text=='第一' and not gate.is_set()
        await generator.aclose();await client.close()
        assert closed
    asyncio.run(run())


@pytest.mark.parametrize('body,code',[
    (event(chunk('不完整')),'stream_disconnected_before_done'),
    (event(chunk('看似完整',finish='stop')),'stream_disconnected_before_done'),
    (event(chunk('部分',finish='length')),'translation_finish_length'),
    (event(chunk(reasoning_content='not user visible')),'unexpected_thinking_output'),
    (b'data: not-json\n\n','invalid_sse_json'),
    (event(chunk(finish='stop'))+b'data: [DONE]\n\n','incomplete_translation_stream'),
])
def test_malformed_truncated_or_thinking_output_never_completes(body,code):
    async def run():
        client=DeepSeekClient(TranslationConfig(),Credential('private-test-sentinel'),transport=httpx.MockTransport(
            lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=body)))
        try:
            with pytest.raises(ProviderError) as error:_=[e async for e in client.stream([])]
            assert error.value.code==code
        finally:await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('status,code,fatal,retryable',[(401,'authentication_failed',True,False),
    (402,'insufficient_balance',True,False),(429,'rate_limited',False,True),(503,'provider_unavailable',False,True)])
def test_error_classification_and_no_response_body_leak(status,code,fatal,retryable):
    async def run():
        secret='private-test-sentinel'
        client=DeepSeekClient(TranslationConfig(),Credential(secret),transport=httpx.MockTransport(
            lambda request:httpx.Response(status,json={'error':secret},headers={'retry-after':'10000'})))
        try:
            with pytest.raises(ProviderError) as error:_=[e async for e in client.stream([])]
            e=error.value
            assert (e.code,e.fatal,e.retryable)==(code,fatal,retryable)
            assert secret not in str(e) and e.retry_after<=2
        finally:await client.close()
    asyncio.run(run())


def test_separate_usage_chunk_and_usage_on_truncated_output():
    async def run():
        for reason in ('stop','length'):
            body=event(chunk('译文',finish=reason,usage={'total_tokens':5}))
            if reason=='stop':body+=event({'choices':[],'usage':{'total_tokens':5}})+b'data: [DONE]\n\n'
            client=DeepSeekClient(TranslationConfig(),Credential('private-test-sentinel'),transport=httpx.MockTransport(
                lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=body)))
            try:
                if reason=='length':
                    with pytest.raises(ProviderError) as error:_=[e async for e in client.stream([])]
                    assert error.value.usage=={'total_tokens':5}
                else:
                    events=[e async for e in client.stream([])]
                    assert events[-1].kind=='done' and len([e for e in events if e.kind=='usage'])==2
            finally:await client.close()
    asyncio.run(run())


def test_unknown_finish_reason_is_redacted_and_output_is_bounded():
    async def run():
        config=replace(TranslationConfig(),max_output_chars=128)
        for value,expected in [(chunk('x',finish='private-test-sentinel'),'translation_finish_unknown'),
                               (chunk('x'*129),'translation_output_too_large')]:
            client=DeepSeekClient(config,Credential('private-test-sentinel'),transport=httpx.MockTransport(
                lambda request:httpx.Response(200,headers={'content-type':'text/event-stream'},content=event(value))))
            try:
                with pytest.raises(ProviderError) as error:_=[e async for e in client.stream([])]
                assert error.value.code==expected and 'private-test-sentinel' not in str(error.value)
            finally:await client.close()
    asyncio.run(run())
