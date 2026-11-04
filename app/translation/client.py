"""Real text-only DeepSeek HTTPS/SSE client. No built-in test response path."""
from __future__ import annotations
import codecs
from dataclasses import dataclass
import json
import httpx
from .config import TranslationConfig
from .credentials import Credential
from .usage import read_usage


class ProviderError(Exception):
    def __init__(self,code:str,*,retryable:bool=False,fatal:bool=False,status:int|None=None,retry_after:float=0,usage:dict|None=None,
                 timeout_phase:str|None=None):
        super().__init__(code)
        self.code,self.retryable,self.fatal,self.status,self.retry_after=code,retryable,fatal,status,retry_after
        self.usage=usage
        self.timeout_phase=timeout_phase


class SSEDecoder:
    def __init__(self,limit:int=65536):
        self.decoder=codecs.getincrementaldecoder('utf-8')('strict')
        self.pending='';self.data=[];self.size=0;self.limit=limit

    def _line(self,line:str) -> list[str]:
        line=line.rstrip('\r')
        if not line:
            event='\n'.join(self.data)
            present=bool(self.data)
            self.data=[];self.size=0
            return [event] if present else []
        if line.startswith(':'):return []
        if line.startswith('data:'):
            value=line[5:]
            if value.startswith(' '):value=value[1:]
            self.size+=len(value)
            if self.size>self.limit:raise ProviderError('sse_event_too_large')
            self.data.append(value)
        return []

    def feed(self,raw:bytes,final:bool=False) -> list[str]:
        try:self.pending+=self.decoder.decode(raw,final=final)
        except UnicodeError:raise ProviderError('invalid_utf8_stream') from None
        events=[]
        while '\n' in self.pending:
            line,self.pending=self.pending.split('\n',1)
            if len(line)>self.limit:raise ProviderError('sse_line_too_large')
            events.extend(self._line(line))
        if len(self.pending)>self.limit:raise ProviderError('sse_line_too_large')
        if final:
            if self.pending:events.extend(self._line(self.pending));self.pending=''
            events.extend(self._line(''))
        return events


@dataclass(frozen=True)
class StreamEvent:
    kind: str
    text: str = ''
    usage: dict|None = None
    model: str = ''


def usage_fields(value:dict) -> dict:
    try:return read_usage(value)
    except (ValueError,TypeError):raise ProviderError('invalid_usage') from None


def http_error(status:int,retry_after:str|None=None) -> ProviderError:
    try:delay=min(2.,max(0.,float(retry_after or 0)))
    except ValueError:delay=0
    if status in (401,403):return ProviderError('authentication_failed',fatal=True,status=status)
    if status==402:return ProviderError('insufficient_balance',fatal=True,status=status)
    if status in (400,404,422):return ProviderError('invalid_request_or_model',fatal=True,status=status)
    if status==429:return ProviderError('rate_limited',retryable=True,status=status,retry_after=delay)
    if status in (408,500,502,503,504):return ProviderError('provider_unavailable',retryable=True,status=status,retry_after=delay)
    return ProviderError('unexpected_http_status',fatal=True,status=status)


class DeepSeekClient:
    def __init__(self,config:TranslationConfig,credential:Credential,*,transport=None):
        self.config=config
        # The injectable standard HTTP transport is used by tests only; production
        # CLI always constructs a real TLS-verified HTTPX transport.
        self.http=httpx.AsyncClient(headers={'Authorization':'Bearer '+credential.value},
            timeout=httpx.Timeout(config.request_timeout_seconds,connect=config.connect_timeout_seconds),
            limits=httpx.Limits(max_connections=config.concurrency,max_keepalive_connections=config.concurrency),
            follow_redirects=False,transport=transport)

    async def stream(self,messages:list[dict]):
        body={'model':self.config.model,'messages':messages,'thinking':{'type':'disabled'},
              'stream':True,'stream_options':{'include_usage':True},'temperature':.1,
              'max_tokens':self.config.max_tokens}
        decoder=SSEDecoder()
        stopped=done=False
        output_count=0
        returned_model=''
        def parse(data):
            nonlocal stopped,done,output_count,returned_model
            if data=='[DONE]':
                done=True
                if not stopped or output_count==0:raise ProviderError('incomplete_translation_stream')
                return [StreamEvent('done',model=returned_model)]
            try:value=json.loads(data)
            except (ValueError,TypeError):raise ProviderError('invalid_sse_json') from None
            if not isinstance(value,dict) or value.get('error'):raise ProviderError('provider_stream_error',retryable=True)
            returned_model=value.get('model',returned_model)
            events=[]
            if value.get('usage') is not None:events.append(StreamEvent('usage',usage=usage_fields(value['usage'])))
            choices=value.get('choices',[])
            if not isinstance(choices,list) or len(choices)>1:raise ProviderError('invalid_stream_choices')
            for choice in choices:
                if not isinstance(choice,dict) or choice.get('index',0)!=0:raise ProviderError('invalid_stream_choice')
                delta=choice.get('delta',{})
                if not isinstance(delta,dict):raise ProviderError('invalid_stream_delta')
                if delta.get('reasoning_content'):raise ProviderError('unexpected_thinking_output')
                if delta.get('tool_calls'):raise ProviderError('unexpected_tool_output')
                text=delta.get('content')
                if text is not None and not isinstance(text,str):raise ProviderError('invalid_stream_content')
                if text:
                    if stopped:raise ProviderError('content_after_finish')
                    output_count+=len(text)
                    if output_count>self.config.max_output_chars:raise ProviderError('translation_output_too_large')
                    events.append(StreamEvent('delta',text=text))
                reason=choice.get('finish_reason')
                if reason:
                    if reason!='stop':
                        known=reason if reason in ('length','content_filter','tool_calls','insufficient_system_resource','aborted') else 'unknown'
                        raise ProviderError('translation_finish_'+known,retryable=known in ('insufficient_system_resource','aborted'),
                                            usage=usage_fields(value['usage']) if value.get('usage') is not None else None)
                    stopped=True
            return events
        try:
            async with self.http.stream('POST',self.config.base_url.rstrip('/')+'/chat/completions',json=body) as response:
                if response.status_code!=200:
                    # Never log the body: errors can echo request data or credentials.
                    raise http_error(response.status_code,response.headers.get('retry-after'))
                if 'text/event-stream' not in response.headers.get('content-type',''):
                    raise ProviderError('expected_sse_response')
                async for chunk in response.aiter_bytes():
                    if len(chunk)>262144:raise ProviderError('sse_chunk_too_large')
                    for data in decoder.feed(chunk):
                        for event in parse(data):yield event
                        if done:return
                for data in decoder.feed(b'',final=True):
                    for event in parse(data):yield event
                    if done:return
                raise ProviderError('stream_disconnected_before_done',retryable=True)
        except httpx.TimeoutException as error:
            phase=next((name for kind,name in ((httpx.ConnectTimeout,'connect'),(httpx.ReadTimeout,'read'),
                (httpx.WriteTimeout,'write'),(httpx.PoolTimeout,'pool')) if isinstance(error,kind)),'transport')
            raise ProviderError('network_timeout',retryable=True,timeout_phase=phase) from None
        except httpx.HTTPError:
            raise ProviderError('network_error',retryable=True) from None

    async def close(self):
        await self.http.aclose()
