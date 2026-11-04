"""GUI flags must protect the cloud boundary and selected process identity."""
from types import SimpleNamespace
import pytest
pytest.importorskip('httpx')
from app.main import main
from app.translation import cli


@pytest.fixture(autouse=True)
def synchronous_cli_coroutine(monkeypatch):
    # These are CLI boundary tests with an immediate fake pipeline, not tests of
    # asyncio or Windows IOCP. No loopback socket/real event loop is needed.
    def run(coroutine):
        try:
            coroutine.send(None)
        except StopIteration as result:
            return result.value
        finally:
            coroutine.close()
        raise AssertionError('unit-test coroutine unexpectedly suspended')
    monkeypatch.setattr(cli.asyncio,'run',run)


def test_source_only_never_reads_credentials_or_constructs_http_client(monkeypatch,capsys):
    def forbidden(*args,**kwargs):raise AssertionError('cloud code called in source-only mode')
    monkeypatch.setattr(cli,'read_credential',forbidden)
    monkeypatch.setattr(cli,'DeepSeekClient',forbidden)
    monkeypatch.setattr(cli,'FileSource',lambda *args:object())
    observed=[]
    async def pipeline(asr,config,source,emit,**kwargs):
        observed.append(kwargs)
        emit('bilingual_summary',asr_complete=True,translation_complete=False,final_subtitles=0)
    monkeypatch.setattr(cli,'run_bilingual',pipeline)
    assert main(['translate-file','--input','not-opened-in-this-unit-test.wav','--source-only'])==3
    assert observed[0]['client'] is None
    assert observed[0]['disabled_reason']=='translation_disabled_by_user'
    assert 'disabled_by_user' in capsys.readouterr().out


def test_gui_stale_vlc_identity_is_rejected_before_capture(monkeypatch,capsys):
    monkeypatch.setattr(cli,'ProcessSelector',lambda:SimpleNamespace(discover=lambda source:([SimpleNamespace(pid=42,created=200)],[])))
    monkeypatch.setattr(cli,'select_process',lambda processes,pid:processes[0])
    def forbidden(*args,**kwargs):raise AssertionError('stale process must never be captured')
    monkeypatch.setattr(cli,'LiveSource',forbidden)
    assert main(['translate-live','--pid','42','--expected-created','100','--source-only'])==1
    assert 'selected audio source process changed' in capsys.readouterr().out


@pytest.mark.parametrize('source',['chrome','edge'])
def test_browser_source_reaches_live_pipeline_without_cloud(monkeypatch,capsys,source):
    seen=[]
    target=SimpleNamespace(pid=42,created=100,path='browser.exe')
    def discover(selected):
        seen.append(selected);return [target],[]
    monkeypatch.setattr(cli,'ProcessSelector',lambda:SimpleNamespace(discover=discover))
    monkeypatch.setattr(cli,'select_process',lambda processes,pid:processes[0])
    monkeypatch.setattr(cli,'LiveSource',lambda *args,**kwargs:object())
    def forbidden(*args):raise AssertionError('source-only browser capture read a cloud credential')
    monkeypatch.setattr(cli,'read_credential',forbidden)
    async def pipeline(asr,config,audio,emit,**kwargs):
        assert kwargs['client'] is None
        emit('bilingual_summary',asr_complete=True,translation_complete=False,final_subtitles=0)
    monkeypatch.setattr(cli,'run_bilingual',pipeline)
    assert main(['translate-live','--source',source,'--pid','42','--expected-created','100','--source-only'])==3
    assert seen==[source]
    assert f'"source": "{source}"' in capsys.readouterr().out


def test_translation_glossary_override_does_not_reenable_asr_hints(monkeypatch,tmp_path):
    monkeypatch.setattr(cli,'FileSource',lambda *args:object())
    path=tmp_path/'terms.json';path.write_text('{}',encoding='utf-8')
    seen=[]
    async def pipeline(asr,config,audio,emit,**kwargs):
        seen.append(config.glossary)
        assert asr.course_terms is None and kwargs['client'] is None
        emit('bilingual_summary',asr_complete=True,translation_complete=False,final_subtitles=0)
    monkeypatch.setattr(cli,'run_bilingual',pipeline)
    assert main(['translate-file','--input','not-opened.wav','--source-only','--glossary',str(path)])==3
    assert seen==[str(path.resolve())]


@pytest.mark.parametrize('command',['translate-live','translate-file','translate-text'])
@pytest.mark.parametrize('mode',['preview','sentence'])
def test_translation_mode_flag_overrides_config_for_all_translation_commands(monkeypatch,command,mode):
    monkeypatch.setattr(cli,'read_credential',lambda:None)
    monkeypatch.setattr(cli,'FileSource',lambda *args:object())
    monkeypatch.setattr(cli,'LiveSource',lambda *args,**kwargs:object())
    target=SimpleNamespace(pid=42,created=100,path='vlc.exe')
    monkeypatch.setattr(cli,'ProcessSelector',lambda:SimpleNamespace(discover=lambda source:([target],[])))
    monkeypatch.setattr(cli,'select_process',lambda processes,pid:target)
    seen=[]
    async def pipeline(asr,config,source,emit,**kwargs):
        seen.append(config.mode);assert asr.course_terms is None
        emit('bilingual_summary',asr_complete=True,translation_complete=False,final_subtitles=0)
    async def text(source,language,config,emit,**kwargs):
        seen.append(config.mode)
        emit('bilingual_summary',translation_complete=False,final_subtitles=0)
    monkeypatch.setattr(cli,'run_bilingual',pipeline);monkeypatch.setattr(cli,'run_text',text)
    args=[command,'--translation-mode',mode]
    args+=['--text','Not stable.','--language','en'] if command=='translate-text' else (
        ['--input','not-opened.wav'] if command=='translate-file' else ['--pid','42'])
    assert main(args)==3 and seen==[mode]


def test_invalid_translation_mode_is_rejected_before_credentials(monkeypatch):
    def forbidden():raise AssertionError('invalid mode must not read credentials')
    monkeypatch.setattr(cli,'read_credential',forbidden)
    with pytest.raises(SystemExit) as error:
        main(['translate-file','--input','not-opened.wav','--translation-mode','unknown'])
    assert error.value.code==2


def test_transcript_directory_flag_reaches_pipeline_without_enabling_cloud(monkeypatch,tmp_path):
    monkeypatch.setattr(cli,'FileSource',lambda *args:object())
    def forbidden():raise AssertionError('source-only save must not read credentials')
    monkeypatch.setattr(cli,'read_credential',forbidden)
    seen=[]
    async def pipeline(asr,config,source,emit,**kwargs):
        seen.append(kwargs['transcript_directory'])
        assert kwargs['client'] is None
        emit('bilingual_summary',asr_complete=True,translation_complete=False,final_subtitles=0)
    monkeypatch.setattr(cli,'run_bilingual',pipeline)
    assert main(['translate-file','--input','not-opened.wav','--source-only','--transcript-directory',str(tmp_path)])==3
    assert seen==[tmp_path]
