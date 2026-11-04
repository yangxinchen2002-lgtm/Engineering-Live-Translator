from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from tools.build_portable import allowed,inventory,write_cmd
from tools.install_tts_runtime import python_command,validate_python
from tools.build_release import package_notes


@pytest.mark.parametrize('name',['course-browser/Default/Cookies','browser-profile/History','.runtime/options.json',
    'Default/Login Data','Local State','saved.m4a','saved.webm','profiles/user/ui-settings.json'])
def test_browser_state_and_other_media_cannot_enter_a_release(name):assert not allowed(Path(name))


@pytest.mark.parametrize('prefix',['ghp_','github_pat_','AIza'])
def test_release_audit_rejects_more_provider_credentials_without_logging_them(tmp_path,prefix):
    sentinel=prefix+'testonly'*6;(tmp_path/'example.json').write_text(json.dumps({'key':sentinel}),'utf-8')
    with pytest.raises(ValueError) as error:inventory(tmp_path)
    assert sentinel not in str(error.value) and 'example.json' in str(error.value)


def test_optional_tts_requires_full_python_and_rejects_incompatible_versions(tmp_path,monkeypatch):
    from tools import install_tts_runtime
    assert python_command()==['py','-3.12']
    assert python_command(tmp_path/'python.exe')==[str((tmp_path/'python.exe').resolve())]
    calls=[]
    def run(command,**kwargs):
        calls.append(command)
        return SimpleNamespace(stdout='[3,12,64]')
    monkeypatch.setattr(install_tts_runtime.subprocess,'run',run)
    validate_python(['py','-3.12']);assert calls[0][:3]==['py','-3.12','-I']
    monkeypatch.setattr(install_tts_runtime.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout='[3,13,64]'))
    with pytest.raises(ValueError):validate_python(['py','-3.13'])


def test_speech_worker_selects_the_relocated_optional_interpreter(tmp_path):
    import runpy,shutil
    source=Path(__file__).resolve().parents[2]/'app/speech/config.py'
    root=tmp_path/'ELT';module=root/'app/speech/config.py';module.parent.mkdir(parents=True)
    shutil.copyfile(source,module)
    assert runpy.run_path(str(module))['PYTHON']==root/'.venv-tts/Scripts/python.exe'
    optional=root/'runtime/tts/python.exe';optional.parent.mkdir(parents=True);optional.touch()
    assert runpy.run_path(str(module))['PYTHON']==optional


def test_latest_extraction_notes_and_checksums_have_three_groups(tmp_path,monkeypatch):
    from tools import build_release
    docs=tmp_path/'repo/docs';docs.mkdir(parents=True)
    for name in ('MODEL_SETUP.md','MODEL_SETUP.en.md'):(docs/name).write_text('Test guide','utf-8')
    monkeypatch.setattr(build_release,'ROOT',tmp_path/'repo')
    packages=tmp_path/'packages';packages.mkdir()
    (packages/'packages.json').write_text(json.dumps({'files':[]}),'utf-8')
    write_cmd(packages/'一键解压.cmd','@echo off\necho Test only\n')
    groups=['01-ELT-Core','02-ASR-Model','03-GPU-Runtime'];package_notes(packages,groups)
    assert json.loads((packages/'packages.json').read_text('utf-8'))['groups']==groups
    assert (packages/'Extract-ELT.cmd').read_bytes()==b'@echo off\r\necho Test only\r\n'
    assert not (packages/'一键解压.cmd').exists()
    assert all(p.name.isascii() for p in packages.iterdir())
    assert 'Qwen' in (packages/'READ-FIRST.txt').read_text('utf-8')
    assert 'MODEL_SETUP.en.md' in (packages/'SHA256SUMS.txt').read_text('utf-8')
