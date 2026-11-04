import json
from pathlib import Path
import pytest
from app.web_follow.desktop import configuration
from app.web_follow.presentation import Presentation,UsageTotals
from app.ui.protocol import SubtitleViewModel
from app.ui.preferences import UISettings,PreferencesStore


OPTIONS=dict(language='en',provider='deepseek',model='deepseek-flash',translate=True,narrate=False,voice=0,lookahead=15)


def state(position=1,cues=None,**changes):
    value=dict(session_id='source',generation=1,position=position,prepared_until=15,paused=False,
               playback_rate=1,has_source=True,worker_pid=10,worker_busy=False,status='ready',paired=True,
               metrics={'device':'cuda'},cues=cues or [],error='')
    return {**value,**changes}


def cue(id,start,end,**changes):
    return dict(id=id,start=start,end=end,source=id+' source',translation='译文',boundary='punctuation',
                source_language='en',asr_confirmed=True,**changes)


def test_clock_controls_visibility_and_history_without_showing_future_text():
    view=Presentation('desktop',OPTIONS);model=SubtitleViewModel()
    result=view.update(state(cues=[cue('a',0,2),cue('b',3,4)]))
    rows=[r for r in result if r['event']=='subtitle']
    assert len(rows)==1 and rows[0]['source_text']=='a source';assert model.update(rows[0])
    assert result[-1]['segment_id']==rows[0]['segment_id']
    result=view.update(state(4,cues=[cue('a',0,2),cue('b',3,4)]))
    assert result[-1]['segment_id'] is None
    assert [r['source_text'] for r in result if r['event']=='subtitle']==['b source']


def test_tentative_context_is_preview_only_not_a_duplicate_transcript_row():
    view=Presentation('desktop',OPTIONS)
    tentative=cue('temporary',0,2);tentative['asr_confirmed']=False
    result=view.update(state(cues=[tentative]))
    assert not any(r['event']=='subtitle' for r in result)
    assert result[-1]['preview_source']=='temporary source'
    result=view.update(state(cues=[cue('confirmed',0,2)]))
    assert [r['source_text'] for r in result if r['event']=='subtitle']==['confirmed source']


def test_final_text_is_immutable_and_seek_gets_new_ids():
    view=Presentation('desktop',OPTIONS)
    row=next(r for r in view.update(state(cues=[cue('a',0,2)])) if r['event']=='subtitle')
    changed=cue('a',0,2);changed['source']='incorrect late replacement'
    assert not any(r['event']=='subtitle' for r in view.update(state(cues=[changed])))
    result=view.update(state(cues=[cue('a',0,2)],generation=2))
    newer=next(r for r in result if r['event']=='subtitle')
    assert newer['session_id']==row['session_id'] and newer['segment_id']>row['segment_id']


def test_partial_start_and_seek_are_never_marked_as_a_complete_course():
    view=Presentation('desktop',OPTIONS)
    assert not view.update(state())[-1]['source_incomplete']
    assert view.update(state(generation=2))[-1]['source_incomplete']
    assert view.update(state(generation=2))[-1]['source_incomplete']
    partial=Presentation('partial',OPTIONS)
    assert partial.update(state(start_position=30))[-1]['source_incomplete']


def usage(n,tokens,amount):
    return dict(usage_revision=n,usage_attempts=n,token_usage={'total_tokens':tokens},attempts_without_usage=0,
                attempts_partial_usage=0,cost_estimate={'low':amount,'high':amount,'complete':True})


def test_usage_survives_idle_and_worker_restarts_without_double_counting():
    totals=UsageTotals();first=usage(2,10,'0.1')
    assert totals.update(10,{'usage':first})['token_usage']['total_tokens']==10
    assert totals.update(None,{'usage':first}) is None
    result=totals.update(20,{'usage':usage(1,3,'0.2')})
    assert result['token_usage']['total_tokens']==13 and result['usage_revision']==3
    assert result['cost_estimate']['low']=='0.3'
    assert totals.update(20,{'usage':usage(1,3,'0.2')}) is None


def test_no_api_calls_are_not_counted_as_a_usage_attempt():
    result=UsageTotals().update(10,{'usage':usage(0,0,'0')})
    assert result['usage_attempts']==result['usage_revision']==0


def test_reused_pid_in_a_new_source_session_does_not_reset_accounting():
    view=Presentation('desktop',OPTIONS)
    first=view.update(state(metrics={'usage':usage(2,10,'0.1')}))
    second=view.update(state(session_id='next-source',metrics={'usage':usage(1,3,'0.2')}))
    total=next(r for r in second if r['event']=='translation_usage')
    assert total['token_usage']['total_tokens']==13 and total['usage_revision']==3


def test_configuration_is_bounded_and_rejects_keys(tmp_path):
    options,seconds,directory=configuration(b'CONFIG '+json.dumps({**OPTIONS,'seconds':60,'transcript_directory':str(tmp_path)}).encode()+b'\n')
    assert options['base_speed']==1 and seconds==60 and directory==tmp_path
    with pytest.raises(ValueError):configuration(b'CONFIG {"api_key":"test-only"}\n')
    with pytest.raises(ValueError):configuration(b'CONFIG '+b'x'*32768+b'\n')


@pytest.mark.parametrize('engine',['qwen','system'])
def test_startup_accepts_all_validated_playback_fields_and_preserves_caption_values(engine):
    from app.web_follow.server import options_from,READING_FIELDS
    settings=options_from({**OPTIONS,'speech_engine':engine,'caption_width':65,'caption_height':96,'caption_font_size':14})
    payload={**settings,'seconds':60,'transcript_directory':None}
    parsed,seconds,directory=configuration(b'CONFIG '+json.dumps(payload).encode()+b'\n')
    assert all(parsed[k]==settings[k] for k in READING_FIELDS)
    assert parsed['caption_width']==65 and parsed['caption_height']==96 and parsed['caption_font_size']==14
    assert seconds==60 and directory is None
    for invalid in ({'caption_width':29},{'caption_width':True},{'caption_height':601},{'caption_font_size':'14'},{'api_key':'test-only'}):
        with pytest.raises(ValueError):configuration(b'CONFIG '+json.dumps({**payload,**invalid}).encode()+b'\n')


def test_web_preferences_are_backward_compatible_and_round_trip(tmp_path):
    store=PreferencesStore(tmp_path/'settings.json')
    store.path.write_text('{"language":"en"}',encoding='utf-8')
    assert store.load().web_follow is False
    from dataclasses import replace
    expected=replace(UISettings(),web_follow=True,web_lookahead=20,web_voice=3,web_base_speed=1)
    store.save(expected);assert store.load()==expected
    with pytest.raises(ValueError):replace(expected,web_base_speed=.75).validate()


def test_assets_and_installed_compatibility_extension_are_identical():
    root=Path(__file__).resolve().parents[2];assets=root/'app/web_follow'
    for path in (assets/'extension').iterdir():
        if path.is_file():assert path.read_bytes()==(root/'experiments/lookahead/extension'/path.name).read_bytes()
    assert (assets/'web/vendor/LICENSE').is_file()
    assert '翻译、语言和朗读设置来自 ELT 主程序' in (assets/'web/connect.html').read_text(encoding='utf-8')
