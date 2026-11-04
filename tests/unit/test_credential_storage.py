"""Credential storage boundary; test values never replace the user's real key."""
import os
import uuid
import pytest
from app.translation.credentials import (TARGET,CredentialStoreError,credential_error_message,
    read_credential,store_credential)

pytestmark=pytest.mark.skipif(os.name!='nt',reason='Windows credential storage')


def test_unicode_write_and_utf16_bytes_read_round_trip(monkeypatch,capsys):
    import win32cred
    sentinel='unit-test-secret-非真实密钥'
    memory={}
    def write(data,flags):
        assert flags==0 and data['TargetName']==TARGET
        assert data['CredentialBlob']==sentinel and isinstance(data['CredentialBlob'],str)
        memory['blob']=data['CredentialBlob'].encode('utf-16-le')
    monkeypatch.setattr(win32cred,'CredWrite',write)
    monkeypatch.setattr(win32cred,'CredRead',lambda *args:{'CredentialBlob':memory['blob']})
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    result=store_credential('  '+sentinel+'  ')
    assert result['stored'] and result['value_logged'] is False
    read=read_credential()
    assert read.value==sentinel and read.source=='windows_credential'
    assert sentinel not in repr(read)+repr(result)
    capture=capsys.readouterr()
    assert sentinel not in capture.out+capture.err


def test_real_binding_accepts_unicode_with_invalid_flags_and_never_writes_a_key(monkeypatch):
    import win32cred,pywintypes
    native_write=win32cred.CredWrite
    target='ELT/Diagnostics/ArgumentValidationOnly/'+uuid.uuid4().hex
    def checked_write(data,flags):
        # Invalid native flags deliberately prohibit writing. This exercises the
        # real pywin32 converter without accessing ELT's actual stored key.
        assert flags==0
        try:native_write({**data,'TargetName':target},0xFFFFFFFF)
        except pywintypes.error:raise
        else:
            win32cred.CredDelete(target,win32cred.CRED_TYPE_GENERIC,0)
            pytest.fail('Windows unexpectedly accepted invalid credential flags')
    monkeypatch.setattr(win32cred,'CredWrite',checked_write)
    with pytest.raises(CredentialStoreError) as captured:store_credential('test-only-placeholder')
    # Old bytes input raises TypeError before Windows and has no Windows code.
    assert captured.value.winerror is not None
    assert captured.value.operation=='write'


@pytest.mark.parametrize('value',['short','contains whitespace','x'*513])
def test_invalid_format_does_not_call_windows(monkeypatch,value):
    import win32cred
    def forbidden(*args):pytest.fail('invalid input reached credential store')
    monkeypatch.setattr(win32cred,'CredWrite',forbidden)
    with pytest.raises(ValueError):store_credential(value)


@pytest.mark.parametrize('code',[5,87,1312])
def test_native_failure_keeps_only_safe_error_code(monkeypatch,code):
    import win32cred
    sentinel='secret-must-not-appear'
    class StoreFailure(Exception):winerror=code
    def fail(*args):raise StoreFailure(sentinel)
    monkeypatch.setattr(win32cred,'CredWrite',fail)
    with pytest.raises(CredentialStoreError) as captured:store_credential(sentinel)
    error=captured.value
    assert error.winerror==code and error.operation=='write'
    assert str(code) in credential_error_message(error)
    assert sentinel not in str(error)+repr(error)+credential_error_message(error)


def test_read_failure_preserves_numeric_code_only(monkeypatch):
    import win32cred
    class StoreFailure(Exception):winerror=5
    def fail(*args):raise StoreFailure('secret-must-not-appear')
    monkeypatch.setattr(win32cred,'CredRead',fail)
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    with pytest.raises(CredentialStoreError) as captured:read_credential()
    assert captured.value.winerror==5 and captured.value.operation=='read'
    assert 'secret-must-not-appear' not in str(captured.value)


def test_unknown_exceptions_cannot_disclose_secret_in_gui():
    sentinel='secret-must-not-appear'
    for error in (RuntimeError(sentinel),ValueError(sentinel),TypeError(sentinel)):
        assert sentinel not in credential_error_message(error)
