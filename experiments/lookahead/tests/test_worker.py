import asyncio
from collections import deque
from dataclasses import replace
from types import SimpleNamespace as NS

import pytest
from app.translation.client import StreamEvent, ProviderError
from app.translation.usage import UsageLedger
from experiments.lookahead.timeline import Cue
from experiments.lookahead.worker import translate_cues


class Client:
    def __init__(self, fail=False, block=False):
        self.fail, self.block, self.closed = fail, block, False
        self.messages = []
    async def stream(self, messages):
        self.messages.append(messages)
        if self.block:
            await asyncio.Event().wait()
        if self.fail:
            raise ProviderError('network_test_failure')
        yield StreamEvent('delta', text='测试译文')
        yield StreamEvent('usage', usage={'prompt_tokens':10, 'completion_tokens':3, 'total_tokens':13})
        yield StreamEvent('done', model='deepseek-flash')
    async def close(self):
        self.closed = True


def setup(monkeypatch, client):
    from app.translation.credentials import Credential
    monkeypatch.setattr('app.translation.credentials.read_credential', lambda provider: Credential('test-key-only', provider=provider))
    monkeypatch.setattr('app.translation.factory.create_client', lambda *a: client)
    return dict(provider='deepseek', model='deepseek-flash')


def test_real_prompt_adapter_context_usage_with_mock_transport_only(monkeypatch):
    client = Client()
    options = setup(monkeypatch, client)
    context = deque(maxlen=5)
    ledger = UsageLedger()
    result = asyncio.run(translate_cues([Cue('a', 0, 1, 'eigenvalue'), Cue('b', 2, 3, 'matrix')],
                                       'en', options, context, ledger, lambda: False))
    assert [c.translation for c in result] == ['测试译文', '测试译文']
    assert ledger.snapshot()['token_usage']['total_tokens'] == 26
    assert len(context) == 2 and client.closed
    assert 'eigenvalue' in client.messages[1][1]['content']


def test_translation_failure_keeps_source(monkeypatch):
    client = Client(fail=True)
    options = setup(monkeypatch, client)
    result = asyncio.run(translate_cues([Cue('a', 0, 1, 'original')], 'en', options, deque(maxlen=5),
                                      UsageLedger(), lambda: False))
    assert result[0].source == 'original' and not result[0].translation
    assert 'network_test_failure' in result[0].translation_error
    assert client.closed


def test_each_translation_is_published_before_batch_finishes(monkeypatch):
    client=Client();options=setup(monkeypatch,client);published=[]
    def publish(cue):
        published.append(cue.id)
        return replace(cue,speech='test-only.wav')
    results=asyncio.run(translate_cues([Cue('a',0,1,'first'),Cue('b',2,3,'second')],'en',options,
        deque(maxlen=5),UsageLedger(),lambda:False,publish))
    assert published==['a','b'] and all(c.speech=='test-only.wav' for c in results)


def test_complete_sentences_not_whisper_segments_are_translation_units(monkeypatch):
    from experiments.lookahead.sentences import plan_sentences
    client=Client();options=setup(monkeypatch,client)
    segments=[NS(words=[NS(start=0,end=2,word='This'),NS(start=2,end=4,word=' long')]),
              NS(words=[NS(start=4,end=8,word=' sentence.'),NS(start=8.2,end=9,word=' Next'),
                        NS(start=9,end=10,word=' one.')])]
    prepared=plan_sentences(segments,0,9,0,17,100,1)
    result=asyncio.run(translate_cues(prepared.cues,'en',options,deque(maxlen=5),UsageLedger(),lambda:False))
    assert [c.source for c in result]==['This long sentence.','Next one.']
    assert len(client.messages)==2
    assert 'This long sentence.' in client.messages[0][1]['content']


def test_seek_cancels_inflight_api_request(monkeypatch):
    client = Client(block=True)
    options = setup(monkeypatch, client)
    async def run():
        calls = 0
        def stale():
            nonlocal calls
            calls += 1
            return calls > 2
        with pytest.raises(InterruptedError):
            await translate_cues([Cue('a', 0, 1, 'original')], 'en', options, deque(maxlen=5), UsageLedger(), stale)
    asyncio.run(run())
    assert client.closed


def test_missing_key_keeps_all_source_cues(monkeypatch):
    monkeypatch.setattr('app.translation.credentials.read_credential', lambda p: None)
    cues = [Cue('a', 0, 1, 'one'), Cue('b', 2, 3, 'two')]
    result = asyncio.run(translate_cues(cues, 'en', dict(provider='deepseek',model='deepseek-flash'),
                                      deque(maxlen=5), UsageLedger(), lambda: False))
    assert [c.source for c in result] == ['one', 'two']
    assert all(c.translation_error for c in result)
