from dataclasses import replace
import json
import pytest
from app.translation.config import TranslationConfig,ROOT
from app.translation.glossary import Glossary,Term
from app.translation.prompt import messages
from app.translation.credentials import Credential,read_credential,validate_key


@pytest.mark.parametrize('changes',[{'base_url':'http://api.deepseek.com'},{'base_url':'https://other.example'},
    {'base_url':'https://user:password@api.deepseek.com'},{'base_url':'https://api.deepseek.com?key=x'},
    {'model':'another-model'},{'concurrency':0},{'concurrency':True},{'max_retries':4},
    {'context_count':6},{'request_timeout_seconds':float('nan')},{'queue_capacity':1000},
    {'mode':'unknown'},{'mode':True}])
def test_config_rejects_unsafe_or_unbounded_values(changes):
    with pytest.raises(ValueError):replace(TranslationConfig(),**changes).validate()


def test_config_relative_glossary_and_no_secret_fields(tmp_path):
    p=tmp_path/'settings.toml';p.write_text('[translation]\nglossary="terms.json"',encoding='utf-8')
    assert TranslationConfig.load(p).glossary==str((tmp_path/'terms.json').resolve())
    p.write_text('[translation]\napi_key="do-not-store"',encoding='utf-8')
    with pytest.raises(ValueError,match='API keys'):TranslationConfig.load(p)
    assert TranslationConfig.load(ROOT/'config/translation.toml').model=='deepseek-flash'


def test_translation_mode_can_be_loaded_without_changing_existing_default(tmp_path):
    path=tmp_path/'translation.toml';path.write_text('[translation]\nmode="sentence"',encoding='utf-8')
    assert TranslationConfig.load(path).mode=='sentence'
    assert TranslationConfig().mode=='preview'


def test_glossary_domains_and_substring_boundaries():
    g=Glossary([Term('kernel','零空间','mathematics','linear map','en'),
                Term('kernel','核函数','machine_learning','kernel method','en'),
                Term('rank','秩','mathematics','','en')])
    selected=g.relevant('The kernel and ranking','en','machine_learning',12,2400)
    assert len(selected)==2 and selected[0]['target_translation']=='核函数'
    assert not g.relevant('kernel','de','',12,2400)
    assert not g.relevant('kernel','en','',0,2400)
    assert not g.relevant('kernel','en','',12,1)


def test_real_glossary_has_four_domains_and_required_fields():
    g=Glossary.load(ROOT/'terminology/engineering.json')
    assert {'control','robotics','mathematics','machine_learning'}<={t.domain for t in g.entries}
    assert g.relevant('Eigenwert und Übertragungsfunktion','de','control',12,2400)


@pytest.mark.parametrize('body',[{'version':2,'entries':[]},{'version':1,'entries':'wrong'},
    {'version':1,'entries':[{'source_term':'x'}]},
    {'version':1,'entries':[{'source_term':'x','target_translation':'中','domain':'math','context_note':'','unknown':1}]}])
def test_invalid_glossary(tmp_path,body):
    p=tmp_path/'terms.json';p.write_text(json.dumps(body),encoding='utf-8')
    with pytest.raises(ValueError):Glossary.load(p)


def test_prompt_is_bounded_and_never_contains_audio_or_full_history():
    config=replace(TranslationConfig(),context_count=3,context_chars=160)
    context=[{'source_text':'source '+str(i),'translated_text':'中文'+str(i)} for i in range(20)]
    value=messages('Eigenwert λ < 0','de',context,Glossary([]),config)
    payload=json.loads(value[1]['content'])
    assert len(payload['context'])<=3 and payload['current_source_text']=='Eigenwert λ < 0'
    assert set(payload)=={'source_language','current_source_text','context','relevant_terminology'}
    assert '否定' in value[0]['content'] and '数据' in value[0]['content']


def test_credential_repr_and_invalid_values_do_not_disclose_secret(monkeypatch):
    secret='private-sentinel-value'
    monkeypatch.setenv('DEEPSEEK_API_KEY',secret)
    credential=read_credential()
    assert credential.value==secret and secret not in repr(credential)
    with pytest.raises(ValueError) as exc:validate_key('private sentinel value')
    assert 'private sentinel' not in str(exc.value)


def test_secret_command_line_rejected_without_echo(capsys):
    from app.main import main
    assert main(['translate-text','--language','en','--text','hello','--api-key','private-sentinel-value'])==2
    captured=capsys.readouterr()
    assert 'private-sentinel-value' not in captured.out+captured.err


def test_credential_encoding_error_is_safe(monkeypatch):
    import os
    if os.name!='nt':pytest.skip('Windows credential path')
    import win32cred
    monkeypatch.delenv('DEEPSEEK_API_KEY',raising=False)
    monkeypatch.setattr(win32cred,'CredRead',lambda *a,**k:{'CredentialBlob':b'x'})
    with pytest.raises(RuntimeError) as error:read_credential()
    assert 'secret omitted' in str(error.value)
