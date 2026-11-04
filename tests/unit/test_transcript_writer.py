import asyncio
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pytest
from app.subtitles.transcript import TranscriptWriter,transcript_filename

START=datetime(2026,10,31,23,59,tzinfo=timezone(timedelta(hours=1)))


def record(index=1,**changes):
    value=dict(session_id='test-session',segment_id=index,revision=2,source_language='de',
        start_sample=index*16000,source_text=f'Quelle {index}: λ < 0.',translated_text=f'译文 {index}：λ < 0。',
        translated_revision=2,source_closed=True,state='final')
    value.update(changes);return value


def writer(directory,**kwargs):
    events=[];now=[0]
    result=TranscriptWriter(directory,'test-session','de',lambda event,**data:events.append((event,data)),
        clock=lambda:now[0],started=START,**kwargs)
    return result,events,now


@pytest.mark.parametrize('seconds,minutes',[(0,0),(59.999,0),(60,1),(119.999,1),(120,2)])
def test_actual_minutes_floor_and_filename_uses_start_date(tmp_path,seconds,minutes):
    async def run():
        value,_,now=writer(tmp_path);value.start();value.source_started();value.offer(record())
        now[0]=int(seconds*1e9);result=await value.close(source_complete=True)
        assert Path(result['transcript_path']).name==f'2026-10-31-德语-{minutes}分钟.txt'
        assert result['transcript_minutes']==minutes and result['transcript_complete']
    asyncio.run(run())


def test_disabled_writer_never_opens_files(tmp_path,monkeypatch):
    async def run():
        def forbidden(*args,**kwargs):raise AssertionError('disabled transcript performed file IO')
        value,events,_=writer(None);monkeypatch.setattr(value,'_open',forbidden)
        value.start();value.offer(record());result=await value.close()
        assert not result['transcript_enabled'] and result['transcript_complete'] and not events
        assert not list(tmp_path.iterdir())
    asyncio.run(run())


def test_all_pairs_sorted_deduplicated_and_autosaved_before_finalization(tmp_path):
    async def run():
        value,events,now=writer(tmp_path);value.start();value.source_started()
        value.offer(record(2,state='preview',translated_text='old prefix',translated_revision=1))
        value.offer(record(2));value.offer(record(1));value.offer(record(1,translated_text='duplicate replacement'))
        value.offer(record(1,revision=1,translated_text='stale source'))
        await value.queue.join()
        assert '译文 2' in value.progress_path.read_text(encoding='utf-8')
        now[0]=125_000_000_000;result=await value.close(source_complete=True)
        text=Path(result['transcript_path']).read_text(encoding='utf-8')
        assert text.index('Quelle 1')<text.index('Quelle 2') and text.count('译文 1')==1
        assert 'duplicate replacement' not in text and 'stale source' not in text and 'old prefix' not in text
        assert result['transcript_records']==2 and result['transcript_translated']==2
        assert [path.name for path in tmp_path.iterdir()]==['2026-10-31-德语-2分钟.txt']
        assert sum(event=='transcript_saved' for event,data in events)==1
        assert value.connection is None and value.file is None
    asyncio.run(run())


def test_unfinished_tail_keeps_source_but_never_mislabels_old_prefix_translation(tmp_path):
    async def run():
        value,_,_=writer(tmp_path);value.start()
        value.offer(record(source_closed=False,state='preview',translated_revision=1,translated_text='旧前缀译文'))
        result=await value.close(source_complete=False);text=Path(result['transcript_path']).read_text(encoding='utf-8')
        assert 'Quelle 1' in text and '未完成翻译' in text and '旧前缀译文' not in text
        assert '停止或中断' in text and result['transcript_untranslated']==1
    asyncio.run(run())


@pytest.mark.parametrize('hint,languages,expected',[('auto',['en'],'英语'),('auto',['de'],'德语'),
    ('auto',['de','en'],'德语+英语'),('auto',[],'未识别语言'),('ja',['ja'],'日语'),
    ('auto',['ja'],'日语'),('auto',['en','ja'],'英语+日语'),
    ('auto',['ja','de','en'],'德语+英语+日语')])
def test_auto_language_and_empty_recording_are_named_honestly(tmp_path,hint,languages,expected):
    async def run():
        value=TranscriptWriter(tmp_path,'test-session',hint,lambda *args,**kwargs:None,started=START);value.start()
        for index,language in enumerate(languages,1):value.offer(record(index,source_language=language))
        result=await value.close(source_complete=True)
        assert Path(result['transcript_path']).name==f'2026-10-31-{expected}-0分钟.txt'
        if not languages:assert '未取得可保存的已确认原文' in Path(result['transcript_path']).read_text(encoding='utf-8')
    asyncio.run(run())


def test_same_date_language_minute_names_never_overwrite_existing_or_concurrent_files(tmp_path):
    async def run():
        original=tmp_path/'2026-10-31-德语-0分钟.txt';original.write_text('keep original',encoding='utf-8')
        first,_,_=writer(tmp_path);second,_,_=writer(tmp_path);first.start();second.start()
        first.offer(record(source_text='first'));second.offer(record(source_text='second'))
        results=await asyncio.gather(first.close(),second.close())
        assert {Path(row['transcript_path']).name for row in results}=={
            '2026-10-31-德语-0分钟 (2).txt','2026-10-31-德语-0分钟 (3).txt'}
        assert original.read_text(encoding='utf-8')=='keep original'
    asyncio.run(run())


def test_full_session_outlives_128_record_display_history(tmp_path):
    async def run():
        value,_,_=writer(tmp_path);value.start()
        for index in range(1,151):
            value.offer(record(index,state='preview',translated_text=''));value.offer(record(index))
            if index%8==0:await value.queue.join()
        result=await value.close(source_complete=True);text=Path(result['transcript_path']).read_text(encoding='utf-8')
        assert result['transcript_records']==150 and result['transcript_translated']==150
        assert 'Quelle 1:' in text and 'Quelle 150:' in text and result['transcript_complete']
    asyncio.run(run())


def test_queue_overflow_is_explicit_and_partial_output_is_not_claimed_complete(tmp_path):
    async def run():
        value,events,_=writer(tmp_path,capacity=1);value.start();value.offer(record(1));value.offer(record(2))
        result=await asyncio.wait_for(value.close(),3)
        assert not result['transcript_complete'] and result['transcript_dropped']==1
        assert '保存过程中发生错误' in Path(result['transcript_path']).read_text(encoding='utf-8')
        assert any(event=='transcript_error' and data['reason']=='transcript_queue_full' for event,data in events)
    asyncio.run(run())


@pytest.mark.parametrize('operation',['open','write','finalize'])
def test_storage_errors_release_handles_and_report_failure(tmp_path,monkeypatch,operation):
    async def run():
        value,events,_=writer(tmp_path)
        def failed(*args,**kwargs):raise OSError('test filesystem unavailable')
        monkeypatch.setattr(value,'_'+operation,failed)
        value.start();value.offer(record());result=await asyncio.wait_for(value.close(),3)
        assert not result['transcript_complete'] and value.file is None and value.connection is None
        assert any(event=='transcript_error' for event,data in events)
        assert not any(event=='transcript_saved' for event,data in events)
    asyncio.run(run())


def test_cross_session_and_invalid_filename_values_cannot_write_foreign_content(tmp_path):
    async def run():
        value,events,_=writer(tmp_path);value.start();value.offer(record(session_id='other'))
        result=await value.close()
        assert not result['transcript_complete'] and result['transcript_records']==0
    asyncio.run(run())
    with pytest.raises(ValueError):transcript_filename(START,'../escape',1)
