import json
import pytest
from app.ui.protocol import EventDecoder,SubtitleViewModel


def subtitle(segment=1,revision=1,candidate_revision=0,**changes):
    value=dict(event='subtitle',session_id='session',segment_id=segment,revision=revision,candidate_revision=candidate_revision,
               source_text='The matrix',candidate_text='',translated_text='',state='preview')
    value.update(changes);return value


def test_utf8_jsonl_arbitrary_packet_boundaries():
    raw=(json.dumps({'event':'subtitle','text':'中文 λ'},ensure_ascii=False)+'\n').encode()
    parser=EventDecoder();events=[]
    for byte in raw:events+=parser.feed(bytes([byte]))
    parser.finish();assert events[0]['text']=='中文 λ'


@pytest.mark.parametrize('data',[b'not-json\n',b'[]\n',b'{"event":3}\n',b'\xff\n'])
def test_invalid_event_is_explicit(data):
    with pytest.raises((ValueError,UnicodeError)):EventDecoder().feed(data)


def test_unfinished_and_oversized_lines_are_rejected():
    parser=EventDecoder(10)
    with pytest.raises(ValueError):parser.feed(b'xxxxxxxxxxx')
    parser=EventDecoder();parser.feed(b'{')
    with pytest.raises(ValueError):parser.finish()


def test_old_or_final_subtitle_cannot_be_overwritten_and_late_history_does_not_jump():
    model=SubtitleViewModel()
    assert model.update(subtitle())
    assert model.update(subtitle(revision=2,source_text='The matrix is singular.'))
    assert not model.update(subtitle(revision=1))
    assert model.update(subtitle(segment=2,source_text='Next sentence'))
    assert model.update(subtitle(revision=2,source_text='The matrix is singular.',state='final',translated_text='矩阵是奇异的。'))
    assert model.current['segment_id']==2
    assert not model.update(subtitle(revision=3,source_text='old changed'))
    assert not model.update(subtitle(segment=2,session_id='old-session'))


def test_candidate_version_and_equal_revision_canonical_source_guard():
    model=SubtitleViewModel();model.update(subtitle(candidate_revision=2))
    assert not model.update(subtitle(candidate_revision=1))
    assert not model.update(subtitle(candidate_revision=3,source_text='different source'))
    assert model.update(subtitle(candidate_revision=3,candidate_text='is'))


def test_view_model_is_bounded_and_validates_types():
    model=SubtitleViewModel(3)
    for i in range(10):model.update(subtitle(segment=i+1))
    assert len(model.records)==3 and model.current['segment_id']==10
    with pytest.raises(ValueError):model.update(subtitle(segment='bad'))
