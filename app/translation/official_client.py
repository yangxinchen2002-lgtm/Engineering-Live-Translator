"""Real official OpenAI Responses, Anthropic Messages and Gemini SSE adapters."""
from __future__ import annotations
import json
import httpx
from .client import ProviderError,SSEDecoder,StreamEvent,http_error,usage_fields


def integer(value):
    if type(value) is not int or not 0<=value<=10**12:raise ProviderError('invalid_usage')
    return value


def normalize_usage(provider,value):
    if not isinstance(value,dict):raise ProviderError('invalid_usage')
    if provider=='openai':
        result={target:integer(value[source]) for source,target in
                (('input_tokens','prompt_tokens'),('output_tokens','completion_tokens'),('total_tokens','total_tokens')) if source in value}
        cached=value.get('input_tokens_details',{})
        if isinstance(cached,dict) and 'cached_tokens' in cached:result['prompt_cache_hit_tokens']=integer(cached['cached_tokens'])
    elif provider=='claude':
        result={}
        if 'input_tokens' in value:
            result['prompt_tokens']=integer(value['input_tokens'])+sum(integer(value[k]) for k in
                ('cache_read_input_tokens','cache_creation_input_tokens') if k in value)
        if 'output_tokens' in value:result['completion_tokens']=integer(value['output_tokens'])
        if 'cache_read_input_tokens' in value:result['prompt_cache_hit_tokens']=integer(value['cache_read_input_tokens'])
    else:
        result={target:integer(value[source]) for source,target in
                (('promptTokenCount','prompt_tokens'),('totalTokenCount','total_tokens'),('cachedContentTokenCount','prompt_cache_hit_tokens')) if source in value}
        # totalTokenCount includes thinking, not just visible candidates. No tools
        # are enabled, so the reported total minus prompt is the full output.
        if 'total_tokens' in result and 'prompt_tokens' in result:
            result['completion_tokens']=integer(result['total_tokens']-result['prompt_tokens'])
        elif 'candidatesTokenCount' in value and 'thoughtsTokenCount' in value:
            result['completion_tokens']=integer(value['candidatesTokenCount'])+integer(value['thoughtsTokenCount'])
    return usage_fields(result)


class StreamState:
    def __init__(self,provider,limit):
        self.provider=provider;self.limit=limit;self.count=0;self.stopped=False;self.done=False
        self.usage={};self.model=''
        self.text_index=None

    def text(self,value):
        if not isinstance(value,str):raise ProviderError('invalid_stream_content')
        if not value:return []
        if self.stopped:raise ProviderError('content_after_finish')
        self.count+=len(value)
        if self.count>self.limit:raise ProviderError('translation_output_too_large')
        return [StreamEvent('delta',text=value)]

    def account(self,value):
        normalized=normalize_usage(self.provider,value)
        return [StreamEvent('usage',usage=normalized)] if normalized else []

    def finish(self):
        if not self.stopped or not self.count:raise ProviderError('incomplete_translation_stream',retryable=not self.stopped)
        self.done=True;return [StreamEvent('done',model=self.model)]

    def parse(self,data):
        try:value=json.loads(data)
        except (ValueError,TypeError):raise ProviderError('invalid_sse_json') from None
        if not isinstance(value,dict):raise ProviderError('invalid_sse_json')
        try:
            if self.provider=='openai':return self.openai(value)
            if self.provider=='claude':return self.claude(value)
            return self.gemini(value)
        except ProviderError:raise
        except (TypeError,AttributeError,KeyError,ValueError):raise ProviderError('invalid_stream_payload') from None

    def openai(self,value):
        kind=value.get('type');response=value.get('response',{});events=[]
        if kind=='response.output_text.delta':
            index=value.get('output_index',0)
            if type(index) is not int or index<0:raise ProviderError('unexpected_stream_output')
            if self.text_index is None:self.text_index=index
            if self.text_index!=index:raise ProviderError('unexpected_stream_output')
            return self.text(value.get('delta'))
        if kind=='response.refusal.delta':raise ProviderError('translation_finish_content_filter')
        if kind in ('error','response.failed'):
            raise ProviderError('provider_stream_error',retryable=True)
        if kind in ('response.completed','response.incomplete'):
            if not isinstance(response,dict):raise ProviderError('invalid_stream_response')
            if response.get('usage') is not None:events+=self.account(response['usage'])
            if kind=='response.incomplete' or response.get('status')!='completed':
                reason=response.get('incomplete_details') or {}
                code='translation_finish_content_filter' if reason.get('reason')=='content_filter' else 'translation_finish_length'
                raise ProviderError(code,usage=normalize_usage('openai',response['usage']) if response.get('usage') is not None else None)
            if any(item.get('type') not in ('message','reasoning') for item in response.get('output',[]) if isinstance(item,dict)):
                raise ProviderError('unexpected_tool_output')
            self.model=response.get('model','');self.stopped=True;return events+self.finish()
        return events

    def claude(self,value):
        kind=value.get('type');events=[]
        if kind=='error':raise ProviderError('provider_stream_error',retryable=True)
        if kind=='message_start':
            message=value.get('message',{})
            self.model=message.get('model','');self.usage.update(message.get('usage') or {})
            if self.usage:events+=self.account(self.usage)
        elif kind=='content_block_start':
            block=value.get('content_block',{})
            if block.get('type') not in ('text','thinking','redacted_thinking'):raise ProviderError('unexpected_tool_output')
            if block.get('type')=='text':events+=self.text(block.get('text',''))
        elif kind=='content_block_delta':
            delta=value.get('delta',{})
            if delta.get('type')=='text_delta':events+=self.text(delta.get('text'))
        elif kind=='message_delta':
            self.usage.update(value.get('usage') or {})
            if self.usage:events+=self.account(self.usage)
            reason=value.get('delta',{}).get('stop_reason')
            if reason:
                if reason not in ('end_turn','stop_sequence'):
                    raise ProviderError('translation_finish_length' if reason=='max_tokens' else 'translation_finish_content_filter',
                                        usage=normalize_usage('claude',self.usage) if self.usage else None)
                self.stopped=True
        elif kind=='message_stop':events+=self.finish()
        return events

    def gemini(self,value):
        if value.get('error'):raise ProviderError('provider_stream_error',retryable=True)
        if value.get('promptFeedback',{}).get('blockReason'):raise ProviderError('translation_finish_content_filter')
        events=[];self.model=value.get('modelVersion',self.model)
        if value.get('usageMetadata') is not None:
            self.usage=value['usageMetadata'];events+=self.account(self.usage)
        candidates=value.get('candidates',[])
        if not isinstance(candidates,list) or len(candidates)>1:raise ProviderError('invalid_stream_choices')
        for candidate in candidates:
            if candidate.get('index',0)!=0:raise ProviderError('invalid_stream_choice')
            for part in candidate.get('content',{}).get('parts',[]):
                if 'functionCall' in part:raise ProviderError('unexpected_tool_output')
                if 'text' in part and not part.get('thought'):events+=self.text(part['text'])
            reason=candidate.get('finishReason')
            if reason:
                if reason!='STOP':
                    raise ProviderError('translation_finish_length' if reason=='MAX_TOKENS' else 'translation_finish_content_filter',
                                        usage=normalize_usage('gemini',self.usage) if self.usage else None)
                self.stopped=True
        # Gemini has no [DONE] marker; consume through EOF for trailing usage.
        return events


class OfficialAPIClient:
    def __init__(self,config,credential,*,transport=None):
        config.validate()
        if credential.provider!=config.provider:raise ValueError('credential does not belong to selected provider')
        self.config=config
        if config.provider=='openai':headers={'Authorization':'Bearer '+credential.value}
        elif config.provider=='claude':headers={'x-api-key':credential.value,'anthropic-version':'2023-06-01'}
        elif config.provider=='gemini':headers={'x-goog-api-key':credential.value}
        else:raise ValueError('unsupported native provider adapter')
        self.http=httpx.AsyncClient(headers=headers,timeout=httpx.Timeout(config.request_timeout_seconds,connect=config.connect_timeout_seconds),
            limits=httpx.Limits(max_connections=config.concurrency,max_keepalive_connections=config.concurrency),
            follow_redirects=False,transport=transport)

    def request(self,messages):
        system='\n'.join(row['content'] for row in messages if row['role']=='system')
        user=[row for row in messages if row['role']!='system'];cfg=self.config
        if cfg.provider=='openai':
            return '/responses',{'model':cfg.model,'instructions':system,'input':user,'max_output_tokens':cfg.max_tokens,'stream':True,'store':False}
        if cfg.provider=='claude':
            return '/messages',{'model':cfg.model,'system':system,'messages':user,'max_tokens':cfg.max_tokens,'stream':True}
        contents=[{'role':'model' if row['role']=='assistant' else 'user','parts':[{'text':row['content']}]} for row in user]
        return f'/models/{cfg.model}:streamGenerateContent?alt=sse',{
            'systemInstruction':{'parts':[{'text':system}]},'contents':contents,
            'generationConfig':{'maxOutputTokens':cfg.max_tokens,'candidateCount':1}}

    async def stream(self,messages):
        path,body=self.request(messages);state=StreamState(self.config.provider,self.config.max_output_chars);decoder=SSEDecoder()
        try:
            async with self.http.stream('POST',self.config.base_url.rstrip('/')+path,json=body) as response:
                if response.status_code!=200:raise http_error(response.status_code,response.headers.get('retry-after'))
                if 'text/event-stream' not in response.headers.get('content-type',''):raise ProviderError('expected_sse_response')
                async for chunk in response.aiter_bytes():
                    if len(chunk)>262144:raise ProviderError('sse_chunk_too_large')
                    for data in decoder.feed(chunk):
                        for event in state.parse(data):yield event
                        if state.done:return
                for data in decoder.feed(b'',final=True):
                    for event in state.parse(data):yield event
                    if state.done:return
                if self.config.provider=='gemini':
                    for event in state.finish():yield event
                else:raise ProviderError('stream_disconnected_before_done',retryable=True)
        except httpx.TimeoutException as error:
            phase=next((name for kind,name in ((httpx.ConnectTimeout,'connect'),(httpx.ReadTimeout,'read'),
                (httpx.WriteTimeout,'write'),(httpx.PoolTimeout,'pool')) if isinstance(error,kind)),'transport')
            raise ProviderError('network_timeout',retryable=True,timeout_phase=phase) from None
        except httpx.HTTPError:raise ProviderError('network_error',retryable=True) from None

    async def close(self):await self.http.aclose()
