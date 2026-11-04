import asyncio
from dataclasses import replace,asdict
import json
import os
import time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication,QDialog
from PySide6.QtTest import QTest,QSignalSpy
from app.translation.providers import PROVIDERS
from app.translation.credentials import Credential,credential_target,read_credential,store_credential,manage_credential
from app.ui.preferences import PreferencesStore,UISettings


@pytest.fixture
def app(monkeypatch):
    from app.ui import controller
    monkeypatch.setattr(controller.BackendController,'refresh_processes',lambda self:None)
    monkeypatch.setattr(controller,'manage_credential',lambda action,provider='deepseek':{'available':False,'source':'unavailable'})
    return QApplication.instance() or QApplication([])


def wait(predicate):
    deadline=time.monotonic()+3
    while not predicate() and time.monotonic()<deadline:QTest.qWait(10)
    assert predicate()


def test_four_keys_use_separate_windows_targets_and_legacy_deepseek_survives(monkeypatch):
    if os.name!='nt':pytest.skip('Windows credential boundary')
    import win32cred
    from app.translation import credentials
    monkeypatch.setattr(credentials,'profile_id',lambda:None)
    memory={}
    monkeypatch.setattr(win32cred,'CredWrite',lambda data,flags:memory.__setitem__(data['TargetName'],data['CredentialBlob'].encode('utf-16-le')))
    monkeypatch.setattr(win32cred,'CredRead',lambda target,kind:{'CredentialBlob':memory[target]})
    monkeypatch.setattr(win32cred,'CredDelete',lambda target,*args:memory.pop(target,None))
    for code,info in PROVIDERS.items():
        monkeypatch.delenv(info.environment,raising=False);store_credential('private-test-'+code,code)
    assert len(memory)==4 and credential_target()=='ELT/DeepSeekAPIKey'
    for code in PROVIDERS:
        key=read_credential(code);assert key.value=='private-test-'+code and key.provider==code
        assert key.value not in repr(key)+repr(manage_credential('status',code))
    manage_credential('delete','openai')
    assert credential_target('deepseek') in memory and credential_target('claude') in memory and len(memory)==3


@pytest.mark.parametrize('code',PROVIDERS)
def test_selected_environment_key_does_not_read_another_provider(monkeypatch,code):
    from app.translation import credentials
    monkeypatch.setattr(credentials,'profile_id',lambda:None)
    for name,info in PROVIDERS.items():monkeypatch.setenv(info.environment,'private-test-'+name)
    assert read_credential(code).value=='private-test-'+code
    assert read_credential(code).provider==code


def test_profile_credentials_are_isolated_and_ignore_user_environment(monkeypatch):
    from app.translation import credentials
    monkeypatch.setattr(credentials,'profile_id',lambda:'portable-test')
    for code,info in PROVIDERS.items():
        monkeypatch.setenv(info.environment,'private-test-env')
        assert credential_target(code)==f'ELT/portable-test/{info.credential_name}'


def test_preferences_remember_provider_and_each_model_without_secrets(app,tmp_path):
    from app.ui.window import MainWindow
    store=PreferencesStore(tmp_path/'preferences.json')
    store.save(replace(UISettings(),translation_provider='openai',translation_models={'openai':'gpt-4.1-mini','gemini':'gemini-3.8-flash'}))
    window=MainWindow(preferences=store);QTest.qWait(30)
    assert window.translation_provider.currentData()=='openai' and window.controller.translation_provider=='openai'
    window.translation_model.setCurrentText('gpt-4.1')
    window.translation_provider.setCurrentIndex(window.translation_provider.findData('gemini'))
    assert window.translation_model.currentText()=='gemini-3.8-flash'
    window.translation_provider.setCurrentIndex(window.translation_provider.findData('openai'))
    assert window.translation_model.currentText()=='gpt-4.1'
    saved=window.settings_snapshot();assert saved.translation_models['openai']=='gpt-4.1'
    window.translation_model.setCurrentText('sk-private-secret')
    assert 'sk-private-secret' not in json.dumps(asdict(window.settings_snapshot()))
    window.close();QTest.qWait(10)


def test_late_status_for_different_provider_cannot_enable_wrong_translation(app):
    from app.ui.window import MainWindow
    window=MainWindow();QTest.qWait(20)
    window.translation_provider.setCurrentIndex(window.translation_provider.findData('claude'))
    window.credentials_ready({'provider':'openai','available':True,'source':'windows_credential'})
    assert window.translation_provider.currentData()=='claude' and not window.credential_status['available']
    assert window.provider_credentials['openai']['available']
    window.credentials_ready({'provider':'claude','available':True,'source':'windows_credential'})
    assert window.translate_check.isEnabled() and window.credential_status['provider']=='claude'
    window.close();QTest.qWait(10)


def test_key_dialog_selects_source_saves_only_it_and_ignores_other_completion(app,monkeypatch):
    from app.ui import controller as module
    from app.ui.window import MainWindow,KeyDialog
    memory={}
    monkeypatch.setattr(module,'store_credential',lambda value,provider='deepseek':memory.__setitem__(provider,value))
    monkeypatch.setattr(module,'manage_credential',lambda action,provider='deepseek':{'available':provider in memory,'source':'windows_credential'})
    window=MainWindow();QTest.qWait(20);dialog=KeyDialog(window.controller,window.credential_status,window);dialog.show()
    dialog.key.setText('private-first-draft');dialog.provider.setCurrentIndex(dialog.provider.findData('gemini'))
    assert not dialog.key.text()
    dialog.key.setText('private-test-gemini');dialog.save.click()
    assert not dialog.key.text() and not dialog.provider.isEnabled()
    dialog._saved('openai',True,'unrelated completion');assert dialog.isVisible()
    wait(lambda:dialog.result()==QDialog.DialogCode.Accepted)
    assert memory=={'gemini':'private-test-gemini'} and not dialog.key.text()
    assert window.provider_credentials['gemini']['available'] and window.translation_provider.currentData()=='deepseek'
    window.close();QTest.qWait(10)


def test_service_and_model_controls_locked_during_session(app):
    from app.ui.window import MainWindow
    window=MainWindow();QTest.qWait(20)
    window.running_changed(True)
    assert not window.translation_provider.isEnabled() and not window.translation_model.isEnabled() and not window.key_button.isEnabled()
    window.running_changed(False);assert window.translation_provider.isEnabled() and window.translation_model.isEnabled()
    window.speech.stop();window.close();QTest.qWait(10)


@pytest.mark.parametrize('provider',['openai','claude','gemini'])
def test_cli_reads_only_selected_key_and_constructs_selected_client(monkeypatch,provider):
    from app.main import main
    from app.translation import cli
    called=[]
    monkeypatch.setattr(cli,'read_credential',lambda selected='deepseek':called.append(('read',selected)) or Credential('private-test-value',provider=selected))
    class Client:
        async def close(self):called.append(('close',provider))
    monkeypatch.setattr(cli,'create_client',lambda cfg,key:called.append(('client',cfg.provider,cfg.model,key.provider)) or Client())
    async def run(text,language,cfg,emit,**kwargs):emit('bilingual_summary',translation_complete=True,final_subtitles=1)
    monkeypatch.setattr(cli,'run_text',run)
    assert main(['translate-text','--text','Not stable.','--language','en','--translation-provider',provider])==0
    assert called[0]==('read',provider) and called[1]==('client',provider,PROVIDERS[provider].models[0],provider)


@pytest.mark.parametrize('provider',PROVIDERS)
def test_source_only_never_reads_any_provider_secret(monkeypatch,provider):
    from app.main import main
    from app.translation import cli
    def forbidden(*args,**kwargs):raise AssertionError('source-only must never access API credentials')
    monkeypatch.setattr(cli,'read_credential',forbidden);monkeypatch.setattr(cli,'create_client',forbidden)
    monkeypatch.setattr(cli,'FileSource',lambda *args:object())
    async def run(asr,cfg,source,emit,**kwargs):
        assert kwargs['client'] is None;emit('bilingual_summary',translation_complete=False,final_subtitles=0)
    monkeypatch.setattr(cli,'run_bilingual',run)
    assert main(['translate-file','--input','not-opened.wav','--language','en','--source-only','--translation-provider',provider])==3


def test_other_provider_key_does_not_enable_deepseek_course_notes(app,monkeypatch):
    from app.ui.window import MainWindow
    window=MainWindow();QTest.qWait(20)
    window.translation_provider.setCurrentIndex(window.translation_provider.findData('openai'))
    window.credentials_ready({'provider':'openai','available':True,'source':'windows_credential'})
    assert not window.notes_key_ready()
    window.credentials_ready({'provider':'deepseek','available':True,'source':'windows_credential'})
    assert window.notes_key_ready() and window.translation_provider.currentData()=='openai'
    window.close();QTest.qWait(10)


@pytest.mark.parametrize('provider',PROVIDERS)
def test_selected_model_reaches_capture_controller_without_key_in_arguments(app,monkeypatch,provider):
    from app.ui.window import MainWindow
    from app.audio.processes import ProcessInfo
    window=MainWindow();QTest.qWait(20);calls=[]
    window.translation_provider.setCurrentIndex(window.translation_provider.findData(provider))
    window.credentials_ready({'provider':provider,'available':True,'source':'windows_credential'})
    window.translate_check.setChecked(True)
    target=ProcessInfo(42,'vlc.exe','C:/vlc.exe',100);window.processes_ready([target],[])
    monkeypatch.setattr(window.controller,'start',lambda *args,**kwargs:calls.append((args,kwargs)))
    window.start_capture()
    assert len(calls)==1 and window.controller.translation_provider==provider
    assert calls[0][1]['translation_model']==PROVIDERS[provider].models[0] and calls[0][0][2] is True
    assert not any('key' in name for name in calls[0][1])
    window.close();QTest.qWait(10)


@pytest.mark.parametrize('name',['openai','claude','anthropic','gemini','google'])
def test_command_line_keys_are_rejected_without_echo(name,capsys):
    from app.main import main
    assert main(['translate-text','--text','hello','--language','en','--'+name+'-api-key','private-secret-sentinel'])==2
    captured=capsys.readouterr();assert 'private-secret-sentinel' not in captured.out+captured.err


@pytest.mark.parametrize('provider',PROVIDERS)
def test_half_typed_model_prefix_is_never_saved_as_a_model_id(provider):
    from app.translation.providers import validate_model
    with pytest.raises(ValueError):validate_model(provider,PROVIDERS[provider].model_prefix)


def test_cancel_and_repeat_save_cannot_claim_that_a_different_key_was_stored(app,monkeypatch):
    import threading
    from app.ui import controller as module
    from app.ui.window import MainWindow,KeyDialog
    started=threading.Event();release=threading.Event();saved=[]
    def store(value,provider='deepseek'):
        if not saved:started.set();assert release.wait(2)
        saved.append((provider,value))
    monkeypatch.setattr(module,'store_credential',store)
    monkeypatch.setattr(module,'manage_credential',lambda action,provider='deepseek':{'available':bool(saved),'source':'windows_credential'})
    window=MainWindow();QTest.qWait(20)
    first=KeyDialog(window.controller,{},window);first.show();first.key.setText('private-test-first');first.save.click()
    wait(started.is_set);first.reject()
    second=KeyDialog(window.controller,{},window);second.show();second.key.setText('private-test-replacement');second.save.click()
    assert second.isVisible() and second.save.isEnabled() and '仍在进行' in second.message.text()
    release.set();wait(lambda:not any(key.startswith('credential_save:') for key in window.controller.operations))
    QTest.qWait(10);assert second.isVisible() and saved==[('deepseek','private-test-first')]
    second.key.setText('private-test-final');second.save.click();wait(lambda:second.result()==QDialog.DialogCode.Accepted)
    assert saved[-1]==('deepseek','private-test-final')
    window.close();QTest.qWait(10)
