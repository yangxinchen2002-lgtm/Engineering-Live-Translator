"""Independent summary choices, real adapters with mock HTTP, and both UI languages."""
import asyncio
from dataclasses import replace,asdict
import io
import json
import os
from pathlib import Path
import pytest
import httpx

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from app.notes.config import request_config
from app.notes.service import create_notes
from app.translation.providers import PROVIDERS
from app.translation.credentials import Credential
from app.translation.factory import create_client
from app.translation.client import ProviderError
from tests.unit.test_multi_provider_api import response_bytes


@pytest.mark.parametrize('provider',PROVIDERS)
@pytest.mark.parametrize('language',['zh','en'])
def test_summary_uses_selected_official_api_model_language_and_usage(tmp_path,provider,language):
    seen=[];clients=[];secret='unit-only-summary-'+provider
    payload={'notes_provider':provider,'notes_model':PROVIDERS[provider].models[0],
             'target_language':language,'records':[{'id':1,'source':'The matrix is not invertible.','translated':''}]}
    text='The matrix is not invertible.' if language=='en' else '矩阵不可逆。'
    def factory(config,key):
        assert key.provider==provider and config.provider==provider
        def handle(request):
            seen.append(request)
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=response_bytes(provider,text))
        client=create_client(config,key,transport=httpx.MockTransport(handle));clients.append(client);return client
    result=asyncio.run(create_notes(payload,tmp_path,Credential(secret,provider=provider),lambda *a,**k:None,client_factory=factory))
    assert result['provider']==provider and result['model']==payload['notes_model'] and result['target_language']==language
    assert len(seen)==2 and result['total_tokens']==52 and clients[0].http.is_closed
    for request in seen:
        assert str(request.url).startswith(PROVIDERS[provider].base_url)
        body=json.loads(request.content);assert body.get('model',payload['notes_model'])==payload['notes_model']
        assert secret not in str(request.url)+request.content.decode()
        if provider=='deepseek':assert body['thinking']=={'type':'disabled'}
        elif provider=='openai':assert request.url.path=='/v1/responses' and body['store'] is False
        elif provider=='claude':assert request.url.path=='/v1/messages'
        else:assert request.url.path.endswith('/'+payload['notes_model']+':streamGenerateContent')
        system=body.get('instructions') or body.get('system') or body.get('systemInstruction',{}).get('parts',[{}])[0].get('text')
        if provider=='deepseek':system=body['messages'][0]['content']
        assert ('Write in English' in system)==(language=='en')
    output=Path(result['path']);notes=output.read_text('utf-8')
    assert text in notes and secret not in notes
    assert ('Detailed notes' in notes)==(language=='en')
    if language=='en':assert output.name.endswith('-AI-Course-Notes.txt') and '【片段' not in seen[0].content.decode()
    else:assert '分段详细笔记' in notes


def test_mismatched_key_is_rejected_before_any_client_or_file(tmp_path):
    calls=[]
    with pytest.raises(ValueError):
        asyncio.run(create_notes({'notes_provider':'openai','records':[{'id':1,'source':'test'}]},tmp_path,
            Credential('unit-only-deepseek'),lambda *a,**k:None,client_factory=lambda *a:calls.append(a)))
    assert not calls and not list(tmp_path.iterdir())


@pytest.mark.parametrize('provider',PROVIDERS)
def test_worker_reads_only_the_chosen_key(monkeypatch,tmp_path,provider):
    from app.notes import worker,service
    from app.translation import credentials
    calls=[];payload={'notes_provider':provider,'records':[{'id':1,'source':'Course material'}]}
    monkeypatch.delenv('ELT_GUI_OWNER_JOB',raising=False)
    monkeypatch.setattr(worker.sys,'argv',['notes','--directory',str(tmp_path)])
    monkeypatch.setattr(worker.sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))
    monkeypatch.setattr(credentials,'read_credential',lambda code:calls.append(('key',code)) or Credential('unit-only-key',provider=code))
    async def create(payload,directory,key,emit):calls.append(('request',key.provider,request_config(payload).model))
    monkeypatch.setattr(service,'create_notes',create)
    assert worker.main()==0
    assert calls==[('key',provider),('request',provider,PROVIDERS[provider].models[0])]


@pytest.mark.parametrize('changes',[{'notes_provider':'unknown'},{'notes_provider':'openai','notes_model':'deepseek-flash'},
                                  {'target_language':'fr'}])
def test_invalid_summary_configuration_does_not_read_keys(monkeypatch,tmp_path,changes):
    from app.notes import worker
    from app.translation import credentials
    calls=[]
    monkeypatch.setattr(worker.sys,'argv',['notes','--directory',str(tmp_path)])
    monkeypatch.setattr(worker.sys,'stdin',io.TextIOWrapper(io.BytesIO(json.dumps(changes).encode())))
    monkeypatch.setattr(credentials,'read_credential',lambda *a:calls.append(a))
    assert worker.main()==2 and calls==[] and not list(tmp_path.iterdir())


@pytest.fixture
def ui(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.ui.controller import BackendController
    from app.ui import controller
    from app.i18n import set_language
    monkeypatch.setattr(BackendController,'refresh_processes',lambda self:None)
    monkeypatch.setattr(controller,'manage_credential',lambda action,provider='deepseek':{'available':False,'source':'unavailable'})
    app=QApplication.instance() or QApplication([])
    from PySide6.QtGui import QFont,QFontDatabase
    from app.ui.window import STYLE
    font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc'
    if 'Microsoft YaHei UI' not in QFontDatabase.families() and font.is_file():QFontDatabase.addApplicationFont(str(font))
    app.setStyle('Fusion');app.setFont(QFont('Microsoft YaHei UI',10));app.setStyleSheet(STYLE)
    yield app
    set_language('zh')


@pytest.mark.parametrize('language',['zh','en'])
@pytest.mark.parametrize('target',['zh','en'])
def test_independent_summary_model_preferences_and_output_language(ui,tmp_path,monkeypatch,language,target):
    from PySide6.QtTest import QTest
    from app.ui.preferences import PreferencesStore,UISettings
    from app.ui.window import MainWindow
    from tests.unit.test_speech_and_course_notes import record
    store=PreferencesStore(tmp_path/'settings.json')
    store.save(replace(UISettings(),ui_language=language,target_language=target,
        notes_provider='openai',notes_models={'openai':'gpt-4.1'}))
    w=MainWindow(preferences=store);QTest.qWait(25)
    try:
        assert w.summary_provider.currentData()=='openai' and w.summary_model.currentText()=='gpt-4.1'
        assert w.translation_provider.currentData()=='deepseek' and not w.notes_key_ready()
        w.credentials_ready({'provider':'openai','available':True})
        assert w.notes_key_ready() and not w.credential_status['available']
        w.summary_provider.setCurrentIndex(w.summary_provider.findData('gemini'))
        w.summary_model.setCurrentText('gemini-3.8-flash')
        w.summary_provider.setCurrentIndex(w.summary_provider.findData('openai'))
        assert w.summary_model.currentText()=='gpt-4.1' and w.translation_provider.currentData()=='deepseek'
        w.credentials_ready({'provider':'openai','available':True})
        w.controller.accept_event(record(0));w.transcript_directory=tmp_path
        calls=[];monkeypatch.setattr(w.notes,'generate',lambda payload,directory:calls.append(payload))
        assert w.generate_current_notes()
        assert calls[0]['notes_provider']=='openai' and calls[0]['notes_model']=='gpt-4.1' and calls[0]['target_language']==target
        preferences=w.settings_snapshot()
        assert preferences.notes_models['gemini']=='gemini-3.8-flash'
        w.summary_model.setCurrentText('sk-test-must-not-save')
        assert 'sk-test-must-not-save' not in json.dumps(asdict(w.settings_snapshot()))
        w.notes_busy_changed(True)
        assert not w.summary_provider.isEnabled() and not w.summary_model.isEnabled() and not w.summary_key_button.isEnabled()
        w.notes_busy_changed(False);assert w.summary_provider.isEnabled()
        assert w.summary_provider.accessibleName()==('Summary API provider' if language=='en' else '总结 API 来源')
        w.show();w.settings_tabs.setCurrentWidget(w.settings_scroll)
        w.settings_scroll.ensureWidgetVisible(w.summary_button);QTest.qWait(30)
        from PySide6.QtWidgets import QWidget
        assert w.settings_scroll.horizontalScrollBar().maximum()==0, [
            (type(x).__name__,x.minimumSizeHint().width(),getattr(x,'text',lambda:'')())
            for x in w.settings_scroll.widget().findChildren(QWidget)
            if x.minimumSizeHint().width()>w.settings_scroll.viewport().width()]
    finally:w.close();QTest.qWait(20)


def test_imported_transcript_uses_summary_choice_and_has_no_translation_side_effect(ui,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from PySide6.QtTest import QTest
    from app.ui.window import MainWindow
    source=tmp_path/'course.txt';source.write_text('The matrix is not invertible.','utf-8')
    w=MainWindow();QTest.qWait(25)
    try:
        w.summary_provider.setCurrentIndex(w.summary_provider.findData('claude'))
        w.credentials_ready({'provider':'claude','available':True})
        monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a:(str(source),'txt'))
        calls=[];monkeypatch.setattr(w.notes,'generate',lambda payload,directory:calls.append(payload))
        w.generate_file_notes()
        assert len(calls)==1 and calls[0]['notes_provider']=='claude'
        assert w.translation_provider.currentData()=='deepseek'
    finally:w.close();QTest.qWait(20)


def test_summary_queue_snapshots_provider_model_without_a_secret(ui,tmp_path,monkeypatch):
    from app.ui.notes import NotesController
    c=NotesController();monkeypatch.setattr(c,'_start_next',lambda:None)
    payload={'records':[{'id':1,'source':'Text'}],'notes_provider':'gemini','notes_model':'gemini-3.8-flash'}
    c.generate(payload,tmp_path);payload['notes_provider']='openai'
    queued=json.loads(c.pending[0][0]);assert queued['notes_provider']=='gemini'
    assert not set(queued)&{'api_key','credential'};c.close()


@pytest.mark.parametrize('change',[{'notes_provider':'bad'},{'notes_models':{'openai':'claude-sonnet-5-5'}},
                                  {'notes_models':{'unknown':'gpt-4.1'}}])
def test_invalid_summary_preferences_are_rejected(change):
    from app.ui.preferences import UISettings
    with pytest.raises(ValueError):replace(UISettings(),**change).validate()
