import os
import pytest
from app.profile import profile_id
from app.translation.credentials import TARGET,credential_target,read_credential,store_credential,manage_credential
from app.ui.preferences import default_path,PreferencesStore

PROFILE='portable-'+'a'*32


def test_distribution_settings_start_blank_without_reading_developer_preferences(monkeypatch,tmp_path):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path));monkeypatch.delenv('ELT_PROFILE_ID',raising=False)
    original=default_path();original.parent.mkdir();original.write_text('{"font_size":32,"save_transcripts":true}')
    monkeypatch.setenv('ELT_PROFILE_ID',PROFILE)
    clean=PreferencesStore(default_path()).load()
    assert clean.font_size==21 and not clean.save_transcripts and not default_path().exists()
    assert original.read_text()=='{"font_size":32,"save_transcripts":true}'


def test_default_profile_preserves_existing_target_and_path(monkeypatch,tmp_path):
    monkeypatch.delenv('ELT_PROFILE_ID',raising=False);monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    assert profile_id() is None and credential_target()==TARGET
    assert default_path()==tmp_path/'ELT'/'ui-settings.json'


@pytest.mark.parametrize('value',['../settings','portable-xyz','other-profile','portable-'+'a'*33])
def test_invalid_profile_cannot_select_arbitrary_paths_or_credentials(monkeypatch,value):
    monkeypatch.setenv('ELT_PROFILE_ID',value)
    with pytest.raises(ValueError):profile_id()


@pytest.mark.skipif(os.name!='nt',reason='Windows credential boundary')
def test_distribution_ignores_environment_key_and_only_uses_its_own_vault_target(monkeypatch):
    import win32cred
    monkeypatch.setenv('ELT_PROFILE_ID',PROFILE);monkeypatch.setenv('DEEPSEEK_API_KEY','external-test-key-must-not-be-used')
    target=f'ELT/{PROFILE}/DeepSeekAPIKey';seen=[];memory={}
    class NotFound(Exception):winerror=1168
    def read(name,kind):
        seen.append(('read',name));assert name==target
        if not memory:raise NotFound()
        return {'CredentialBlob':memory['value'].encode('utf-16-le')}
    def write(data,flags):
        assert data['TargetName']==target;memory['value']=data['CredentialBlob'];seen.append(('write',target))
    def delete(name,*args):assert name==target;memory.clear();seen.append(('delete',name))
    monkeypatch.setattr(win32cred,'CredRead',read);monkeypatch.setattr(win32cred,'CredWrite',write)
    monkeypatch.setattr(win32cred,'CredDelete',delete)
    assert read_credential() is None
    store_credential('distribution-test-only-key');assert read_credential().value=='distribution-test-only-key'
    manage_credential('delete');assert not memory and all(name==target for _,name in seen)
