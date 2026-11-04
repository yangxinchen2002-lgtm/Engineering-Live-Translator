import asyncio
from dataclasses import replace
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from app.speech.config import SpeechConfig,split_for_speech
from app.notes.transcript import CourseTranscript
from app.notes.service import chunks_for,create_notes
from app.translation.client import StreamEvent,ProviderError
from app.translation.credentials import Credential


def record(index,text='原文',translated='中文',**changes):
    return {'event':'subtitle','session_id':'s','segment_id':index,'revision':1,'candidate_revision':0,
            'source_text':text,'candidate_text':'','translated_text':translated,'state':'final',
            'source_closed':True,'translated_revision':1,'source_language':'de',**changes}


def test_speech_split_preserves_every_character_and_bounds_long_phrases():
    text='第一句。\n'+('中文与 English words mixed，'*30)+'最后一句！'
    chunks=split_for_speech(text,60)
    assert ''.join(chunks)==text and max(map(len,chunks))<=60
    assert SpeechConfig(True,'cpu','uncle_fu',0).validate()
    for change in ({'device':'automatic'},{'voice':'missing'},{'volume':101}):
        with pytest.raises(ValueError):replace(SpeechConfig(),**change).validate()


def test_full_course_is_not_limited_by_recent_display_and_rejects_old_translation():
    course=CourseTranscript()
    for index in range(400):course.offer(record(index,text=f'原文{index}',translated=f'中文{index}'))
    course.offer(record(0,translated='错误旧译文',revision=0,translated_revision=0))
    assert len(course.snapshot()['records'])==400
    assert course.snapshot()['records'][0]['translated']=='中文0'
    course.offer(record(401,translated='旧前缀',state='preview',revision=2,translated_revision=1))
    assert course.snapshot()['records'][-1]['translated']==''
    assert course.snapshot()['untranslated']==1
    course.offer(record(402,session_id='other'))
    assert len(course.snapshot()['records'])==401


def test_course_overflow_is_explicit_and_does_not_replace_good_data():
    course=CourseTranscript(limit=30)
    course.offer(record(0,text='a',translated='b'))
    course.offer(record(1,text='x'*100,translated='y'))
    assert course.incomplete and len(course.snapshot()['records'])==1


def test_stopped_capture_marks_course_material_incomplete():
    from PySide6.QtWidgets import QApplication
    from app.ui.controller import BackendController
    app=QApplication.instance() or QApplication([])
    controller=BackendController();controller.accept_event(record(0))
    controller.accept_event({'event':'asr_summary','complete':False})
    assert controller.course.snapshot()['incomplete']
    controller.render_timer.stop();controller.cleanup_idle();app.processEvents()


def test_notes_chunking_covers_all_sections_without_empty_requests():
    payload={'records':[{'id':i,'source':f'第{i}段原文。'*100,'translated':f'第{i}段中文。'*100} for i in range(12)]}
    chunks=chunks_for(payload,2000)
    for index in range(12):
        assert f'【片段{index}】' in ''.join(chunks)
        assert f'第{index}段中文。' in ''.join(chunks)
    assert all(chunks) and len(chunks)>1


class FakeNotesClient:
    def __init__(self,config,credential):self.calls=[];self.closed=False
    async def stream(self,messages):
        self.calls.append(messages)
        yield StreamEvent('delta',text=f'测试返回第{len(self.calls)}部分：保留详细推导与条件。')
        yield StreamEvent('usage',usage={'total_tokens':30})
        yield StreamEvent('done')
    async def close(self):self.closed=True


def test_notes_keep_detailed_parts_and_reserve_new_names(tmp_path):
    client=None
    def factory(config,credential):
        nonlocal client
        client=FakeNotesClient(config,credential);return client
    payload={'name':'课程','records':[{'id':i,'source':f'关键原文{i}。'*500,'translated':f'关键译文{i}。'*500} for i in range(3)]}
    events=[]
    def emit(event,**values):events.append((event,values))
    first=asyncio.run(create_notes(payload,tmp_path,Credential('test','fixture'),emit,client_factory=factory))
    assert client.closed and len(client.calls)==first['parts']+1
    assert all('关键译文' in call[-1]['content'] for call in client.calls[:-1])
    text=open(first['path'],encoding='utf-8').read()
    assert '分段详细笔记' in text and '测试返回第1部分' in text and '课程总览' in text
    second=asyncio.run(create_notes(payload,tmp_path,Credential('test','fixture'),emit,client_factory=factory))
    assert first['path']!=second['path'] and open(first['path'],encoding='utf-8').read()==text
    assert not list(tmp_path.glob('*.tmp'))


def test_failed_ai_request_never_saves_fake_or_partial_notes(tmp_path):
    class Failed(FakeNotesClient):
        async def stream(self,messages):
            yield StreamEvent('delta',text='不完整的内容')
            raise ProviderError('authentication_failed',fatal=True)
    with pytest.raises(ProviderError):
        asyncio.run(create_notes({'records':[{'id':1,'source':'原文','translated':'中文'}]},tmp_path,
            Credential('test','fixture'),lambda *a,**k:None,client_factory=Failed))
    assert not list(tmp_path.iterdir())


def test_speech_waits_for_earlier_final_and_never_reads_preview(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.ui.speech import SpeechController
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.config=SpeechConfig(True);speech.active=True
    speech.offer(record(0,translated='预览',state='preview',source_closed=False))
    speech.offer(record(1,translated='第二句'))
    assert not speech.queue
    speech.offer(record(0,translated='第一句'))
    assert [text for text,_ in speech.queue]==['第一句','第二句']
    speech.offer(record(0,translated='重复第一句'))
    assert [text for text,_ in speech.queue]==['第一句','第二句']
    speech.close();app.processEvents()
