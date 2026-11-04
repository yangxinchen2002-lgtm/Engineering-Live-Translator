import json
import threading
from dataclasses import asdict
import httpx
import pytest
from app.web_follow.server import Lab,Server,options_from
from app.web_follow.media import Source
from app.web_follow.timeline import Cue


@pytest.fixture
def bridge(tmp_path):
    lab=Lab();saved=tmp_path/'web-settings.json'
    server=Server(lab,preferences_path=saved,desktop_options=options_from(
        dict(translate=True,narrate=True,speech_engine='qwen',tts_model='1.7B',tts_voice='lecture_male')))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    client=httpx.Client(base_url=server.origin,trust_env=False,timeout=5)
    extension='a'*32;origin='chrome-extension://'+extension
    result=client.post('/bridge/pair',headers={'Origin':origin,'X-ELT-Extension-Id':extension,'X-ELT-Lab-Token':server.token},json={})
    assert result.status_code==200
    client.headers.update({'Origin':origin,'X-ELT-Extension-Id':extension,'X-ELT-Bridge-Token':result.json()['token']})
    try:yield lab,server,client,saved
    finally:client.close();server.shutdown();server.server_close();lab.close();thread.join(2)


def test_real_extension_settings_and_idle_changes_persist_without_starting_asr(bridge):
    lab,server,client,saved=bridge
    settings=client.get('/bridge/settings');assert settings.status_code==200
    value=settings.json();assert value['translate'] and value['playback']['tts_model']=='1.7B'
    assert any(v['id']=='lecture_male' for v in value['tts_voices'])
    generation=lab.timeline.generation
    changed=client.post('/bridge/playback',json={'options':{'base_speed':1.3,'volume':44,'source_percent':35,'duck_source':False}})
    assert changed.status_code==200
    result=changed.json();assert result['playback']['playback_revision']==1 and result['session_id']==''
    assert result['playback']['source_percent']==35 and result['playback']['volume']==44
    assert lab.process is None and lab.timeline.generation==generation
    stored=json.loads(saved.read_text(encoding='utf-8'));assert stored['source_percent']==35 and not stored['duck_source']
    assert 'token' not in stored and 'api_key' not in stored


def test_extension_reading_auth_and_field_bounds(bridge):
    lab,server,client,saved=bridge
    original=dict(lab.options)
    assert client.get('/bridge/settings',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/bridge/settings',headers={'X-ELT-Bridge-Token':'wrong'}).status_code==403
    assert client.post('/bridge/playback',headers={'X-ELT-Extension-Id':'b'*32},json={'options':{'volume':1}}).status_code==403
    for changes in ({'api_key':'test-only'},{'translate':False},{'source_percent':0},{'duck_source':1},{'volume':101},{'base_speed':.9}):
        assert client.post('/bridge/playback',json={'options':changes}).status_code==400
    assert lab.options==original


def test_active_extension_session_guards_and_voice_revision(bridge):
    lab,server,client,saved=bridge
    # Unit fixture state only; no course fetch, model, API or audio is started.
    lab.source=Source('https://video.opencast.tum.de/test.mp4',True,'video/mp4')
    server.bridge.owner='owner-'+'a'*20;server.bridge.session=lab.session_id
    cue=Cue('1-0-1000',0,2,'Test source.',translation='测试。',speech='0-1-0-1000.wav')
    lab.timeline.cues=[cue];generation=lab.timeline.generation
    valid={'owner':server.bridge.owner,'session_id':lab.session_id,'options':{'tts_model':'0.6B'}}
    assert client.post('/bridge/playback',json={**valid,'owner':'stale'}).status_code==400
    assert client.post('/bridge/playback',json={**valid,'session_id':'stale'}).status_code==400
    assert client.post('/bridge/playback',json={'options':{'volume':20}}).status_code==400
    result=client.post('/bridge/playback',json=valid);assert result.status_code==200
    assert result.json()['playback']['speech_revision']==1 and lab.timeline.generation==generation
    assert not lab.timeline.cues[0].speech and lab.timeline.cues[0].source==cue.source
    assert not lab.apply_speech(asdict(cue),0)


def test_extension_cannot_change_a_native_session_and_save_failure_is_explicit(bridge,monkeypatch):
    lab,server,client,saved=bridge
    lab.source=Source('https://video.opencast.tum.de/test.mp4',True,'video/mp4')
    assert client.post('/bridge/playback',json={'options':{'volume':25}}).status_code==400
    lab.source=None
    from pathlib import Path
    replace=Path.replace
    def fail(path,target):
        if path==saved.with_suffix('.tmp'):raise PermissionError('test-only')
        return replace(path,target)
    monkeypatch.setattr(Path,'replace',fail)
    result=client.post('/bridge/playback',json={'options':{'volume':25}})
    assert result.status_code==200 and result.json()['warning']
    assert lab.options['volume']==25
