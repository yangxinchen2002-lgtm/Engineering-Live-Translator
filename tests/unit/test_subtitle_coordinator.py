from dataclasses import asdict,replace
import pytest
from app.subtitles.coordinator import SubtitleCoordinator,sentence_end
from app.subtitles.models import SubtitleState
from app.translation.config import TranslationConfig


def setup(config=None):
    events=[];requests=[];history=[]
    c=SubtitleCoordinator(config or TranslationConfig(),lambda event,**data:events.append((event,data)),realtime=False)
    c.submit=requests.append;c.on_final=history.append
    return c,requests,events,history


def feed(c,revision,text='',candidate='',endpoint=False,start=100):
    def words(value):
        return [dict(text=w,start=start+i*100,end=start+(i+1)*100,start_ns=0,end_ns=0) for i,w in enumerate(value.split())]
    c.consume(session_id=c.session_id,revision=revision,source_language='de',confirmed_words=words(text),
              candidate_words=words(candidate),endpoint=endpoint,stability_reason='local_agreement')


def test_candidate_immediate_but_not_sent_for_translation():
    c,requests,events,_=setup()
    feed(c,1,candidate='Die Matrix ist')
    assert not requests
    r=next(iter(c.records.values()))
    assert not r.source_text and r.candidate_text=='Die Matrix ist' and r.state==SubtitleState.PREVIEW


def test_asr_stability_does_not_make_final():
    c,requests,_,_=setup()
    feed(c,1,'Die Matrix ist nicht',candidate='invertierbar')
    assert requests and not requests[-1].source_closed
    assert c.records[1].state==SubtitleState.PREVIEW
    request=requests[-1];c.begin(request,'preview');c.complete(request,'preview','矩阵不是')
    assert c.records[1].state==SubtitleState.PREVIEW
    feed(c,2,'invertierbar.',endpoint=True,start=500)
    final_request=requests[-1]
    assert final_request.source_closed and final_request.revision>request.revision
    assert c.records[1].state==SubtitleState.PREVIEW
    c.begin(final_request,'final');c.complete(final_request,'final','矩阵不可逆。')
    assert c.records[1].state==SubtitleState.FINAL


def test_old_revision_partial_and_complete_cannot_overwrite_new_source():
    c,requests,_,history=setup()
    feed(c,1,'Die Matrix ist nicht')
    old=requests[-1];c.begin(old,'old')
    feed(c,2,'invertierbar.',endpoint=True,start=500)
    new=requests[-1];c.begin(new,'new')
    assert not c.partial(old,'old','旧译文')
    assert not c.complete(old,'old','旧译文')
    c.complete(new,'new','矩阵不可逆。')
    locked=c.records[1]
    assert not c.complete(new,'new','重复返回')
    assert not c.partial(old,'old','迟到')
    assert c.records[1]==locked and len(history)==1


def test_old_attempt_and_cross_session_rejected():
    c,requests,_,_=setup();c.submit_text('The matrix is singular.','en')
    request=requests[-1];c.begin(request,'attempt1');c.begin(request,'attempt2')
    assert not c.complete(request,'attempt1','旧重试')
    assert not c.complete(replace(request,session_id='another'),'attempt2','别的会话')
    assert c.complete(request,'attempt2','矩阵是奇异的。')


def test_stale_partial_is_not_counted_as_first_available():
    c,requests,events,_=setup();feed(c,1,'Die Matrix ist nicht')
    old=requests[-1];c.begin(old,'a');feed(c,2,'invertierbar.',start=500,endpoint=True)
    assert not c.partial(old,'a','旧结果')
    assert not any(e=='subtitle_translation_first_available' for e,d in events)
    new=requests[-1];c.begin(new,'b');c.partial(new,'b','矩阵不可逆。');c.complete(new,'b','矩阵不可逆。')
    assert sum(e=='subtitle_translation_first_available' for e,d in events)==1


def test_candidate_update_does_not_invalidate_stable_prefix_translation():
    c,requests,_,_=setup();feed(c,1,'Die Matrix ist nicht',candidate='singulär')
    request=requests[-1];c.begin(request,'a')
    feed(c,2,candidate='invertierbar')
    assert c.current_request(request)
    assert c.partial(request,'a','矩阵不是')
    assert c.records[1].candidate_text=='invertierbar'


def test_candidate_only_updates_never_resubmit_unchanged_translation():
    c,requests,_,_=setup();now=[0];c.clock=lambda:now[0]
    feed(c,1,'Die Matrix ist nicht')
    now[0]=10_000_000_000;feed(c,2,candidate='invertierbar')
    assert len(requests)==1


@pytest.mark.parametrize('word,language,expected',[('z.B.','de',False),('A.','en',False),
    ('3.','de',False),('e.g.','en',False),('invertierbar.','de',True),('stable?','en',True),('0.5','en',False)])
def test_sentence_boundaries(word,language,expected):assert sentence_end(word,language)==expected


def test_multiple_sentences_and_empty_endpoint_close_current():
    c,requests,_,_=setup();feed(c,1,'A ist stabil. B ist instabil.',endpoint=True)
    assert len(c.records)==2 and all(r.source_closed for r in c.records.values())
    c,requests,_,_=setup();feed(c,1,'Die Matrix ist nicht');feed(c,2,endpoint=True)
    assert c.records[1].source_closed and requests[-1].source_closed


def test_duplicate_asr_revision_and_words_do_not_duplicate_source():
    c,_,_,_=setup();feed(c,1,'Die Matrix');feed(c,1,'Die Matrix');feed(c,2,'Die Matrix')
    assert c.records[1].source_text=='Die Matrix'
    with pytest.raises(ValueError):c.consume(session_id='wrong',revision=3,source_language='de',
        confirmed_words=[],candidate_words=[],endpoint=False,stability_reason='')


def test_bounded_records_and_explicit_untranslated_eviction():
    c,_,events,_=setup(replace(TranslationConfig(),record_capacity=16))
    for i in range(20):c.submit_text('A matrix.','en')
    assert len(c.records)==16 and c.evicted_untranslated==4
    assert any(event=='subtitle_evicted' for event,_ in events)
    assert not c.summary()['translation_complete']


def test_final_context_in_source_order_and_no_future_context():
    c,requests,_,_=setup()
    feed(c,1,'Erstens.',start=100);feed(c,2,'Zweitens.',start=300)
    first,second=requests
    c.begin(second,'b');c.complete(second,'b','第二。')
    assert not c.context(first)
    c.begin(first,'a');c.complete(first,'a','第一。')
    assert [r.source_text for r in c.final_context]==['Erstens.','Zweitens.']


def test_manual_text_context_cannot_include_later_completed_request():
    c,requests,_,_=setup()
    c.submit_text('first','en');c.submit_text('second','en')
    first,second=requests
    c.begin(second,'b');c.complete(second,'b','第二')
    assert c.context(first)==[]


def test_sentence_mode_keeps_live_source_and_candidate_updates_without_preview_requests():
    c,requests,events,history=setup(replace(TranslationConfig(),mode='sentence'))
    feed(c,1,'Die Matrix ist nicht',candidate='singulär')
    assert not requests and c.records[1].source_text=='Die Matrix ist nicht'
    assert c.records[1].translation_status=='waiting_sentence'
    c.clock=lambda:10_000_000_000
    feed(c,2,candidate='invertierbar')
    assert not requests and c.records[1].candidate_text=='invertierbar'
    assert any(name=='subtitle' and data['candidate_text']=='invertierbar' for name,data in events)
    feed(c,3,'invertierbar.',endpoint=True,start=500)
    assert len(requests)==1 and requests[0].source_closed
    assert requests[0].source_text=='Die Matrix ist nicht invertierbar.'
    request=requests[0];assert c.begin(request,'only-attempt')
    assert c.complete(request,'only-attempt','矩阵不可逆。')
    feed(c,3,'invertierbar.',endpoint=True,start=500)
    assert len(requests)==1 and len(history)==1 and c.records[1].state==SubtitleState.FINAL


@pytest.mark.parametrize('boundary',['punctuation','endpoint','eof'])
def test_sentence_mode_submits_once_when_source_closes(boundary):
    c,requests,_,_=setup(replace(TranslationConfig(),mode='sentence'))
    feed(c,1,'Die Matrix ist nicht')
    assert not requests
    if boundary=='punctuation':feed(c,2,'invertierbar.',start=500)
    elif boundary=='endpoint':feed(c,2,endpoint=True)
    else:c.end_source();c.end_source()
    assert len(requests)==1 and requests[0].source_closed


def test_sentence_mode_does_not_close_on_abbreviation_or_candidate_punctuation():
    c,requests,_,_=setup(replace(TranslationConfig(),mode='sentence'))
    feed(c,1,'Die Matrix ist z.B.',candidate='singulär.')
    assert not requests and not c.records[1].source_closed
    feed(c,2,'singulär.',start=500)
    assert len(requests)==1 and requests[0].source_text=='Die Matrix ist z.B. singulär.'


def test_sentence_mode_long_input_stays_bounded_without_losing_text():
    c,requests,_,_=setup(replace(TranslationConfig(),mode='sentence',max_source_words=4))
    feed(c,1,'eins zwei drei vier fünf sechs')
    assert len(requests)==1 and c.records[1].close_reason=='bounded_phrase'
    assert c.records[2].source_text=='fünf sechs' and not c.records[2].source_closed
    c.end_source()
    assert len(requests)==2 and all(request.source_closed for request in requests)
    assert ' '.join(request.source_text for request in requests)=='eins zwei drei vier fünf sechs'
