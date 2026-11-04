import asyncio
from collections import Counter
from dataclasses import replace
import json
import pytest
from app.translation.config import ROOT,TranslationConfig
from app.translation.evaluation import load_cases,review_row,screen
from app.subtitles.history import HistoryWriter
from app.subtitles.models import Subtitle,SubtitleState


def test_dataset_is_balanced_and_references_are_explicitly_unreviewed():
    data=load_cases(ROOT/'tests/fixtures/m2_engineering_sentences.json')
    assert data['reference_status']=='draft_requires_human_review'
    assert Counter(c['language'] for c in data['cases'])=={'de':50,'en':50}
    assert Counter(c['domain'] for c in data['cases'])=={'control':25,'robotics':25,'mathematics':25,'machine_learning':25}
    tags={tag for c in data['cases'] for tag in c['tags']}
    assert {'negation','math','condition','causality','subordinate','long_sentence','mixed_language'}<=tags
    row=review_row(data['cases'][0])
    assert row['translated_text'] is None and row['human_review']['status']=='pending'


def test_screens_are_flags_and_do_not_claim_semantic_correctness():
    flags=screen('Do not set x = 5.','设 x = 6。')
    assert {v['kind'] for v in flags}=={'numeric_literal_requires_review','possible_missing_negation_requires_review'}
    assert screen('Set x = 5.','令 x = 5。')==[]


def test_prepare_review_makes_no_api_calls_and_no_synthetic_translations(tmp_path):
    pytest.importorskip('httpx',reason='install translation extra for M2 evaluation tool')
    from tools.evaluate_translation import evaluate
    class Forbidden:
        def stream(self,*args):raise AssertionError('network was not authorized')
    dataset=load_cases(ROOT/'tests/fixtures/m2_engineering_sentences.json')
    async def run():
        result=await evaluate(dataset,TranslationConfig(),Forbidden(),tmp_path,False)
        assert not result['real_api_executed'] and result['completed']==0
        rows=json.loads((tmp_path/'review.json').read_text(encoding='utf-8'))
        assert all(row['translated_text'] is None and row['api_status']=='not_run' for row in rows)
    asyncio.run(run())


def test_history_is_bounded_independent_and_refuses_overwrite(tmp_path):
    async def run():
        events=[];path=tmp_path/'history.jsonl'
        writer=HistoryWriter(path,1,lambda event,**data:events.append((event,data)))
        record=Subtitle('session',1,1,'en','source','译文',0,1,state=SubtitleState.FINAL,source_closed=True)
        writer.offer(record);writer.offer(replace(record,segment_id=2))
        assert writer.queue.qsize()==1 and writer.failed
        writer.start();summary=await writer.close()
        assert summary['history_complete'] is False and any(e=='history_error' for e,d in events)
        with pytest.raises(FileExistsError):HistoryWriter(path,1,lambda *a,**k:None)
        disabled=HistoryWriter(None,1,lambda *a,**k:None)
        disabled.offer(record);assert not (await disabled.close())['history_enabled']
    asyncio.run(run())


def test_history_io_failure_does_not_change_subtitle_state(tmp_path,monkeypatch):
    async def run():
        events=[];writer=HistoryWriter(tmp_path/'history.jsonl',2,lambda event,**data:events.append((event,data)))
        def failed(line):raise OSError('test disk failure')
        monkeypatch.setattr(writer,'_write',failed)
        writer.start()
        record=Subtitle('session',1,1,'en','source','译文',0,1,state=SubtitleState.FINAL)
        writer.offer(record);summary=await writer.close()
        assert not summary['history_complete'] and record.state==SubtitleState.FINAL
        assert any(e=='history_error' for e,d in events)
    asyncio.run(run())
