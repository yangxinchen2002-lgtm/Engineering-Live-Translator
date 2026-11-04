"""Chronological eviction, wire-size bounds and text-free timeout diagnostics."""
import asyncio
from dataclasses import replace
import json
import pytest
from app.translation.config import TranslationConfig
from app.translation.context import bounded_context,context_chars,json_text
from app.translation.prompt import prepare_messages,SYSTEM_PROMPT,PromptBudgetExceeded
from app.translation.glossary import Glossary,Term
from app.translation.client import DeepSeekClient,ProviderError,StreamEvent
from app.translation.credentials import Credential
from tests.unit.test_translation_worker import setup,Client


def pair(index,size=20):
    return {'source_text':f'{index}: '+'x'*size,'translated_text':f'{index}：'+'中'*size}


def test_eviction_keeps_latest_contiguous_suffix_and_does_not_mutate_history():
    history=[pair(i) for i in range(10)];snapshot=json_text(history)
    retained=bounded_context(history,5,context_chars(history[-2:]))
    assert retained==history[-2:] and json_text(history)==snapshot
    assert bounded_context(history,3,6000)==history[-3:]


def test_oversized_newest_entry_cannot_resurrect_older_context():
    history=[pair(1,2),pair(2,2000)]
    assert bounded_context(history,5,200)==[]
    assert bounded_context(history+[pair(3,2)],5,200)==[pair(3,2)]


@pytest.mark.parametrize('count,limit',[(0,2800),(5,0),(0,0),(5,1)])
def test_disabled_or_empty_budget_sends_no_context(count,limit):
    assert bounded_context([pair(1)],count,limit)==[]


def test_budget_includes_json_separators_and_unicode_escaping():
    values=[{'source_text':'λ="x"\n\\','translated_text':'不存在。'},pair(2)]
    boundary=context_chars(values)
    assert bounded_context(values,5,boundary)==values
    assert bounded_context(values,5,boundary-1)==values[1:]
    assert context_chars(values)==len(json_text(values))


@pytest.mark.parametrize('bad',[True,0,2047,24001,6000.,float('nan')])
def test_prompt_limit_config_validates_integer_bounds(bad):
    with pytest.raises(ValueError):replace(TranslationConfig(),max_prompt_chars=bad).validate()


def test_total_prompt_budget_evicts_old_context_before_terms_and_preserves_source():
    config=replace(TranslationConfig(),max_prompt_chars=2048,context_chars=6000,glossary_chars=4000)
    glossary=Glossary([Term('Eigenwert','特征值',f'domain{i}','上下文注释'*55) for i in range(12)])
    history=[pair(i,80) for i in range(5)];source='Der Eigenwert ist nicht positiv: λ ≤ 0, A="M", \\frac{1}{s}.'
    prompt,metadata=prepare_messages(source,'de',history,glossary,config);payload=json.loads(prompt[1]['content'])
    assert len(json_text(prompt))<=2048 and metadata['prompt_chars']==len(json_text(prompt))
    assert metadata['prompt_utf8_bytes']==len(json_text(prompt).encode('utf-8'))
    assert prompt[0]['content']==SYSTEM_PROMPT and payload['current_source_text']==source
    assert metadata['context_entries']==0 and metadata['context_entries_dropped']==5
    assert metadata['glossary_entries_dropped']>0 and metadata['glossary_entries']>0
    original_terms=glossary.relevant(source,'de','',12,4000)
    assert payload['relevant_terminology']==original_terms[:metadata['glossary_entries']]
    assert len(history)==5 and len(glossary.entries)==12
    assert source not in json_text(metadata) and all(type(value) is int for value in metadata.values())


def test_prompt_pruning_does_not_split_whole_source_translation_pairs():
    history=[pair(i,300) for i in range(5)]
    prompt,metrics=prepare_messages('The system is not stable.','en',history,Glossary([]),TranslationConfig())
    payload=json.loads(prompt[1]['content']);retained=payload['context']
    assert retained and retained==history[-len(retained):]
    assert context_chars(retained)<=2800 and len(json_text(prompt))<=6000
    assert metrics['context_entries']==len(retained)


def test_whole_current_source_is_never_silently_cut_to_meet_budget():
    source='\x00'*800
    with pytest.raises(PromptBudgetExceeded) as error:
        prepare_messages(source,'en',[],Glossary([]),replace(TranslationConfig(),max_prompt_chars=2048))
    assert error.value.required>2048 and source not in str(error.value)


def test_persistent_context_is_bounded_for_long_session_and_transcript_is_retained():
    from app.subtitles.coordinator import SubtitleCoordinator
    from app.subtitles.models import SubtitleState
    events=[];saved=[];requests=[]
    config=replace(TranslationConfig(),context_chars=320)
    c=SubtitleCoordinator(config,lambda name,**data:events.append((name,data)),realtime=False)
    c.submit=requests.append;c.on_final=saved.append
    for index in range(300):
        c.submit_text(f'{index}: The matrix is not invertible.','en');request=requests[-1]
        assert c.begin(request,str(index));assert c.complete(request,str(index),'这个矩阵不可逆。'*5)
        assert len(c.final_context)<=5
        pairs=[{'source_text':r.source_text,'translated_text':r.translated_text} for r in c.final_context]
        assert context_chars(pairs)<=320 and c.final_context[-1].segment_id==index+1
    assert len(saved)==300 and saved[0].source_text.startswith('0:')
    assert saved[0].state==SubtitleState.FINAL and len(c.records)==128
    pruned=[data for name,data in events if name=='translation_context_pruned']
    assert pruned and all(data['context_chars']<=320 for data in pruned)
    assert all(not any(key in data for key in ('source_text','translated_text')) for data in pruned)


def test_out_of_order_manual_completions_use_source_order_and_no_future_context():
    from app.subtitles.coordinator import SubtitleCoordinator
    requests=[];c=SubtitleCoordinator(TranslationConfig(),lambda *a,**k:None,realtime=False)
    c.submit=requests.append
    for text in ('first','second','third'):c.submit_text(text,'en')
    for index in (1,0):
        request=requests[index];c.begin(request,str(index));c.complete(request,str(index),'译文'+str(index))
    assert [r.segment_id for r in c.final_context]==[1,2]
    assert [row['source_text'] for row in c.context(requests[2])]==['first','second']
    assert c.context(requests[0])==[]


@pytest.mark.parametrize('phase',['connect','read','write','pool'])
def test_timeout_phase_is_preserved_without_logging_exception_text(phase):
    import httpx
    async def run():
        kind={'connect':httpx.ConnectTimeout,'read':httpx.ReadTimeout,'write':httpx.WriteTimeout,'pool':httpx.PoolTimeout}[phase]
        async def handle(request):raise kind('private request body should never be logged')
        client=DeepSeekClient(TranslationConfig(),Credential('private-test-sentinel'),transport=httpx.MockTransport(handle))
        try:
            with pytest.raises(ProviderError) as error:_=[e async for e in client.stream([])]
            assert error.value.code=='network_timeout' and error.value.timeout_phase==phase
            assert 'private' not in str(error.value)
        finally:await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('partial',[False,True])
def test_deadline_records_prompt_size_elapsed_time_and_whether_output_started(partial):
    async def run():
        class Slow(Client):
            async def stream(self,messages):
                if partial:yield StreamEvent('delta',text='部分')
                await asyncio.Event().wait()
        config=replace(TranslationConfig(),max_retries=0,request_timeout_seconds=.02,connect_timeout_seconds=.01)
        c,w,events=setup(Slow(),config);c.submit_text('Source should not appear in diagnostics.','en')
        await w.close()
        submitted=next(data for name,data in events if name=='translation_submitted')
        failure=next(data for name,data in events if name=='translation_error')
        assert failure['timeout_phase']=='request' and failure['code']=='request_deadline'
        assert failure['first_output_received']==partial
        assert (failure['first_output_seconds'] is not None)==partial
        assert failure['request_seconds']>=.015 and failure['timeout_seconds']==.02
        assert failure['prompt_chars']==submitted['prompt_chars']<=6000
        assert 'Source should not' not in json_text(failure) and '部分' not in json_text(failure)
        assert c.records[1].source_text=='Source should not appear in diagnostics.'
    asyncio.run(run())


def test_overbudget_required_source_is_not_sent_or_billed_and_remains_visible():
    async def run():
        client=Client();c,w,events=setup(client,replace(TranslationConfig(),max_prompt_chars=2048))
        c.submit_text('\x00'*800,'en');stats=await w.close()
        assert client.calls==0 and stats['translation_attempts']==0
        assert c.records[1].source_text=='\x00'*800 and c.records[1].translation_status=='translation_prompt_too_large'
        failure=next(data for name,data in events if name=='translation_error')
        assert failure['request_not_sent'] and failure['required_prompt_chars']>2048
    asyncio.run(run())


def test_diagnostics_keep_latest_prompt_metrics_without_text():
    from app.diagnostics.runtime import RuntimeMetrics
    metrics=RuntimeMetrics();metrics.event({'event':'translation_submitted','context_entries':3,'context_chars':2100,
        'prompt_chars':2900,'prompt_char_limit':6000,'source_text':'never copy this'})
    latest=metrics.snapshot()['latest']['translation_prompt']
    assert latest['context_entries']==3 and latest['prompt_chars']==2900 and 'source_text' not in latest
