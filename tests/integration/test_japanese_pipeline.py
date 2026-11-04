"""Multilingual ASR events -> real HTTP/SSE parser -> subtitle -> saved TXT.

ASR output and HTTP transport are test doubles, never production inference.
"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path

import pytest

httpx = pytest.importorskip('httpx')
from app.asr.config import ASRConfig
from app.translation.client import DeepSeekClient
from app.translation.config import TranslationConfig
from app.translation.credentials import Credential
from app.translation import runtime
from app.languages import LANGUAGE_LABELS

SAMPLES=[('ja',['この','行列','は','正則','です。'],'この行列は正則です。'),
    ('zh',['这个','矩阵','确实','是','正则的。'],'这个矩阵确实是正则的。'),
    ('fr',['Cette','matrice','est','bien','inversible.'],'Cette matrice est bien inversible.'),
    ('ru',['Эта','матрица','является','строго','невырожденной.'],'Эта матрица является строго невырожденной.'),
    ('it',['Questa','matrice','è','davvero','invertibile.'],'Questa matrice è davvero invertibile.'),
    ('ko',['이','행렬은','현재','분명히','정칙입니다.'],'이 행렬은 현재 분명히 정칙입니다.')]


@pytest.mark.parametrize('mode', ['preview', 'sentence'])
@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('language,pieces,full_source',SAMPLES)
def test_multilingual_request_modes_sse_usage_and_transcript(monkeypatch, tmp_path, mode, enabled,language,pieces,full_source):
    async def run():
        events, requests = [], []
        def emit(event, **data):
            events.append((event, data))
        async def pipeline(config, source, on_asr, realtime, *, session_id):
            assert config.language == language and config.course_terms is None
            def words(indices):
                return [dict(text=pieces[i], start=i*1000, end=(i+1)*1000) for i in indices]
            on_asr('asr_update',session_id=session_id,revision=1,source_language=language,
                confirmed_words=words(range(4)),candidate_words=words([4]),endpoint=False,
                stability_reason='local_agreement')
            if mode == 'preview' and enabled:
                for _ in range(100):
                    if any(name == 'translation_completed' for name, _ in events):
                        break
                    await asyncio.sleep(.005)
                assert len(requests) == 1
            else:
                await asyncio.sleep(.01)
                assert not requests
            on_asr('asr_update',session_id=session_id,revision=2,source_language=language,
                confirmed_words=words([4]),candidate_words=[],endpoint=True,stability_reason='endpoint_commit')
            return {'complete':True,'inference_jobs':2}
        monkeypatch.setattr(runtime, 'run_pipeline', pipeline)
        def handle(request):
            body = json.loads(request.content)
            payload = json.loads(body['messages'][1]['content'])
            requests.append(payload)
            assert payload['source_language'] == language
            assert LANGUAGE_LABELS[language] in body['messages'][0]['content']
            assert body['thinking'] == {'type':'disabled'}
            text = '这个矩阵是正则的。' if payload['current_source_text']==full_source else '这个矩阵是正则的'
            chunks = [dict(choices=[dict(index=0,delta={'content':text},finish_reason=None)]),
                dict(choices=[dict(index=0,delta={},finish_reason='stop')],
                     usage=dict(prompt_tokens=20,completion_tokens=5,total_tokens=25))]
            stream = ''.join('data: '+json.dumps(chunk,ensure_ascii=False)+'\n\n' for chunk in chunks)+'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=stream.encode())
        config = replace(TranslationConfig(), mode=mode)
        client = DeepSeekClient(config,Credential('test-only-not-a-real-key'),transport=httpx.MockTransport(handle)) if enabled else None
        await runtime.run_bilingual(ASRConfig(language=language),config,None,emit,client=client,realtime=False,
            transcript_directory=tmp_path)
        summary = next(data for name,data in events if name == 'bilingual_summary')
        assert summary['asr_complete'] and summary['transcript_complete']
        path = Path(summary['transcript_path'])
        assert f'-{LANGUAGE_LABELS[language]}-0分钟.txt' in path.name
        contents = path.read_text(encoding='utf-8')
        assert '原文：'+full_source in contents
        if enabled:
            assert len(requests) == (2 if mode == 'preview' else 1)
            assert summary['translation_complete'] and '中文：这个矩阵是正则的。' in contents
            final = [data for name,data in events if name == 'subtitle' and data['state'] == 'final']
            assert final[-1]['source_text'] == full_source
            usage = [data for name,data in events if name == 'translation_usage'][-1]
            assert usage['token_usage']['total_tokens'] == 25*len(requests)
        else:
            assert not summary['translation_complete'] and not requests
            assert '[未完成翻译，仅保存已确认原文]' in contents
    asyncio.run(run())
