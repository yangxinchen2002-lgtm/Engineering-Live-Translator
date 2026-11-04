import asyncio
from dataclasses import replace
import json
import pytest
httpx=pytest.importorskip('httpx',reason='install translation extra for M2 integration tests')
from app.asr.config import ASRConfig
from app.translation.client import DeepSeekClient
from app.translation.config import TranslationConfig
from app.translation.credentials import Credential
from app.translation.runtime import run_bilingual,run_text


def test_asr_to_sse_to_final_history_is_wired_and_hotwords_off(monkeypatch,tmp_path):
    from app.translation import runtime
    async def pipeline(config,source,emit,realtime,*,session_id):
        assert config.course_terms is None
        emit('asr_update',session_id=session_id,revision=1,source_language='en',
             confirmed_words=[{'text':w,'start':i*100,'end':(i+1)*100} for i,w in enumerate('The system is not stable.'.split())],
             candidate_words=[],endpoint=True,stability_reason='endpoint_commit')
        await asyncio.sleep(.01)
        return {'complete':True,'inference_jobs':1}
    monkeypatch.setattr(runtime,'run_pipeline',pipeline)
    async def run():
        requests=[]
        async def handle(request):
            body=json.loads(request.content);requests.append(body)
            chunks=[{'choices':[{'index':0,'delta':{'content':'系统不稳定。'},'finish_reason':None}]},
                    {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}],
                     'usage':{'prompt_tokens':20,'completion_tokens':5,'total_tokens':25}}]
            stream=''.join('data: '+json.dumps(v,ensure_ascii=False)+'\n\n' for v in chunks)+'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=stream.encode())
        config=TranslationConfig();events=[]
        client=DeepSeekClient(config,Credential('test-only-private-value'),transport=httpx.MockTransport(handle))
        history=tmp_path/'history.jsonl'
        await run_bilingual(ASRConfig(course_terms='disabled-by-m2'),config,None,
                            lambda event,**data:events.append((event,data)),client=client,realtime=False,history_path=history)
        final=[d for e,d in events if e=='subtitle' and d['state']=='final']
        assert final and final[-1]['translated_text']=='系统不稳定。'
        assert json.loads(history.read_text(encoding='utf-8'))['state']=='final'
        summary=next(d for e,d in events if e=='bilingual_summary')
        assert summary['asr_complete'] and summary['translation_complete'] and summary['history_written']==1
        assert requests and requests[0]['thinking']['type']=='disabled'
    asyncio.run(run())


def test_provider_failure_does_not_stop_asr_updates(monkeypatch):
    from app.translation import runtime
    observed=[]
    async def pipeline(config,source,emit,realtime,*,session_id):
        for revision in range(1,5):
            emit('asr_update',session_id=session_id,revision=revision,source_language='en',
                 confirmed_words=[{'text':'Matrix.','start':revision*100,'end':revision*100+50}],
                 candidate_words=[],endpoint=True,stability_reason='local_agreement')
            observed.append(revision);await asyncio.sleep(.01)
        return {'complete':True,'inference_jobs':4}
    monkeypatch.setattr(runtime,'run_pipeline',pipeline)
    async def run():
        config=TranslationConfig();events=[]
        client=DeepSeekClient(config,Credential('test-only-private-value'),transport=httpx.MockTransport(
            lambda request:httpx.Response(402,json={'error':'not logged'})))
        await run_bilingual(ASRConfig(),config,None,lambda event,**data:events.append((event,data)),client=client,realtime=False)
        summary=next(d for e,d in events if e=='bilingual_summary')
        assert observed==[1,2,3,4] and summary['asr_complete'] and not summary['translation_complete']
        assert not any(e=='subtitle' and d['state']=='final' for e,d in events)
        assert len([1 for e,d in events if e=='translation_error'])==1
    asyncio.run(run())


def test_history_is_independent_opt_in_and_refuses_overwrite(tmp_path):
    async def run():
        path=tmp_path/'history.jsonl';path.write_text('keep',encoding='utf-8')
        with pytest.raises(FileExistsError):
            await run_text('source','en',TranslationConfig(),lambda *a,**k:None,history_path=path)
        assert path.read_text()=='keep'
    asyncio.run(run())


def test_source_failure_is_explicit_and_never_reported_translation_complete(monkeypatch):
    from app.translation import runtime
    async def failed(*args,**kwargs):raise RuntimeError('target_exited_select_again_for_new_PID')
    monkeypatch.setattr(runtime,'run_pipeline',failed)
    async def run():
        events=[]
        with pytest.raises(RuntimeError):
            await run_bilingual(ASRConfig(),TranslationConfig(),None,lambda event,**data:events.append((event,data)))
        summary=next(d for e,d in events if e=='bilingual_summary')
        assert summary['asr_complete'] is False and summary['translation_complete'] is False
        assert any(e=='bilingual_source_error' and 'target_exited' in d['message'] for e,d in events)
    asyncio.run(run())


def test_startup_output_failure_still_closes_client_and_history(monkeypatch,tmp_path):
    from app.translation import runtime
    writers=[];closed=[]
    original=runtime.HistoryWriter
    def factory(*args,**kwargs):
        writer=original(*args,**kwargs);writers.append(writer);return writer
    monkeypatch.setattr(runtime,'HistoryWriter',factory)
    class Client:
        async def close(self):closed.append(True)
    def emit(event,**data):
        if event=='translation_status':raise OSError('test output sink failed')
    async def run():
        with pytest.raises(OSError):
            await run_text('source','en',TranslationConfig(),emit,client=Client(),history_path=tmp_path/'history.jsonl')
        assert closed and writers[0].file.closed and writers[0].task.done()
    asyncio.run(run())


@pytest.mark.parametrize('mode,expected_requests',[('preview',3),('sentence',1)])
def test_incremental_source_to_http_sse_request_count_respects_translation_mode(monkeypatch,mode,expected_requests):
    """Mock only the ASR input and HTTP server; use real scheduling/prompt/SSE/state."""
    from app.translation import runtime
    async def run():
        requests=[];events=[];completed=asyncio.Event()
        def emit(event,**data):
            events.append((event,data))
            if event=='translation_completed':completed.set()
        async def pipeline(config,source,on_asr,realtime,*,session_id):
            offset=0
            for revision,chunk in enumerate(('The system is not','stable under','all operating conditions.'),1):
                completed.clear()
                words=[{'text':text,'start':offset+i*100,'end':offset+(i+1)*100} for i,text in enumerate(chunk.split())]
                offset=words[-1]['end']
                on_asr('asr_update',session_id=session_id,revision=revision,source_language='en',confirmed_words=words,
                    candidate_words=[],endpoint=revision==3,stability_reason='local_agreement')
                if mode=='sentence' and revision<3:
                    await asyncio.sleep(.01)
                    assert not requests
                    visible=[row for name,row in events if name=='subtitle'][-1]
                    assert visible['source_text'] and visible['translation_status']=='waiting_sentence'
                else:
                    try:await asyncio.wait_for(completed.wait(),1)
                    except TimeoutError:
                        pytest.fail(f'No completion at revision {revision}: requests={len(requests)}, events={events[-10:]}')
                await asyncio.sleep(.002)
            return {'complete':True,'inference_jobs':3}
        monkeypatch.setattr(runtime,'run_pipeline',pipeline)
        async def handle(request):
            body=json.loads(request.content);requests.append(body)
            chunks=[{'choices':[{'index':0,'delta':{'content':'仅用于 HTTP 集成测试的译文。'},'finish_reason':None}]},
                    {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}],
                     'usage':{'prompt_tokens':20,'completion_tokens':5,'total_tokens':25}}]
            stream=''.join('data: '+json.dumps(chunk,ensure_ascii=False)+'\n\n' for chunk in chunks)+'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=stream.encode())
        # Isolate mode gating from wall-clock throttling; Windows asyncio sleep
        # can wake before one QPC millisecond because of its clock resolution.
        config=replace(TranslationConfig(),mode=mode,preview_interval_seconds=1e-9)
        client=DeepSeekClient(config,Credential('test-only-private-value'),transport=httpx.MockTransport(handle))
        await run_bilingual(ASRConfig(),config,None,emit,client=client,realtime=False)
        assert len(requests)==expected_requests
        assert json.loads(requests[-1]['messages'][-1]['content'])['current_source_text']=='The system is not stable under all operating conditions.'
        submitted=[row for name,row in events if name=='translation_submitted']
        assert [row['phase'] for row in submitted]==(['final'] if mode=='sentence' else ['preview','preview','final'])
        final=[row for name,row in events if name=='subtitle' and row['state']=='final']
        assert len(final)==1 and final[0]['source_text']=='The system is not stable under all operating conditions.'
        assert all(body['thinking']=={'type':'disabled'} for body in requests)
    asyncio.run(run())


def test_session_txt_is_saved_from_actual_final_state_in_source_order(monkeypatch,tmp_path):
    from app.translation import runtime
    async def pipeline(config,source,emit,realtime,*,session_id):
        emit('audio_source_ready',signal='unverified')
        for index,text in enumerate(('First sentence.','Second sentence.'),1):
            emit('asr_update',session_id=session_id,revision=index,source_language='en',
                confirmed_words=[{'text':text,'start':index*100,'end':index*100+50}],
                candidate_words=[],endpoint=True,stability_reason='endpoint_commit')
        await asyncio.sleep(.03)
        return {'complete':True}
    monkeypatch.setattr(runtime,'run_pipeline',pipeline)
    async def run():
        async def handle(request):
            text=json.loads(json.loads(request.content)['messages'][-1]['content'])['current_source_text']
            await asyncio.sleep(.02 if text=='First sentence.' else .001)
            chunks=[{'choices':[{'index':0,'delta':{'content':'测试译文：'+text},'finish_reason':None}]},
                    {'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
            data=''.join('data: '+json.dumps(chunk,ensure_ascii=False)+'\n\n' for chunk in chunks)+'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=data.encode())
        config=replace(TranslationConfig(),mode='sentence');events=[]
        client=DeepSeekClient(config,Credential('test-only-private-value'),transport=httpx.MockTransport(handle))
        await run_bilingual(ASRConfig(language='en'),config,None,lambda event,**data:events.append((event,data)),
            client=client,realtime=False,transcript_directory=tmp_path)
        summary=next(data for event,data in events if event=='bilingual_summary')
        from pathlib import Path
        path=Path(summary['transcript_path']);text=path.read_text(encoding='utf-8')
        assert path.name.endswith('-英语-0分钟.txt')
        assert summary['transcript_complete'] and summary['transcript_records']==summary['transcript_translated']==2
        assert text.index('原文：First sentence.')<text.index('原文：Second sentence.')
        assert text.count('测试译文：First sentence.')==1
    asyncio.run(run())


def test_interrupted_source_preserves_unfinished_confirmed_tail_in_txt(monkeypatch,tmp_path):
    from app.translation import runtime
    async def interrupted(config,source,emit,realtime,*,session_id):
        emit('asr_update',session_id=session_id,revision=1,source_language='de',
            confirmed_words=[{'text':'Die Matrix ist nicht','start':0,'end':100}],candidate_words=[],endpoint=False,
            stability_reason='local_agreement')
        raise RuntimeError('test_source_closed')
    monkeypatch.setattr(runtime,'run_pipeline',interrupted)
    async def run():
        events=[]
        with pytest.raises(RuntimeError,match='test_source_closed'):
            await run_bilingual(ASRConfig(),replace(TranslationConfig(),mode='sentence'),None,
                lambda event,**data:events.append((event,data)),realtime=False,transcript_directory=tmp_path)
        summary=next(data for event,data in events if event=='bilingual_summary')
        from pathlib import Path
        text=Path(summary['transcript_path']).read_text(encoding='utf-8')
        assert 'Die Matrix ist nicht' in text and '未完成翻译' in text
        assert summary['transcript_complete'] and not summary['asr_complete'] and summary['transcript_untranslated']==1
    asyncio.run(run())


def test_transcript_storage_failure_does_not_stop_source_updates(monkeypatch,tmp_path):
    from app.translation import runtime
    def storage_failed(*args):raise OSError('test storage unavailable')
    monkeypatch.setattr(runtime.TranscriptWriter,'_write',storage_failed)
    observed=[]
    async def pipeline(config,source,emit,realtime,*,session_id):
        for index in range(1,5):
            emit('asr_update',session_id=session_id,revision=index,source_language='en',
                confirmed_words=[{'text':'Confirmed source.','start':index*100,'end':index*100+50}],
                candidate_words=[],endpoint=True,stability_reason='endpoint_commit')
            observed.append(index);await asyncio.sleep(.01)
        return {'complete':True}
    monkeypatch.setattr(runtime,'run_pipeline',pipeline)
    async def run():
        events=[]
        await run_bilingual(ASRConfig(language='en'),TranslationConfig(),None,
            lambda event,**data:events.append((event,data)),realtime=False,transcript_directory=tmp_path)
        summary=next(data for event,data in events if event=='bilingual_summary')
        assert observed==[1,2,3,4] and summary['asr_complete'] and not summary['transcript_complete']
        assert any(event=='transcript_error' for event,data in events)
    asyncio.run(run())
