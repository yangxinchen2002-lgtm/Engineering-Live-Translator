import importlib.util
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('export_source',ROOT/'tools/export_source.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_source_allowlist_excludes_personal_material_and_environments(tmp_path):
    for name in module.ROOT_FILES:
        (tmp_path/name).write_text('example',encoding='utf-8')
    for name in ('README.md','README.github.md','app/main.py','app/__pycache__/private.py',
                 'tools/source.py','docs/ARCHITECTURE.md','config/asr.toml','terminology/engineering.json',
                 'tests/unit/test_example.py','tests/integration/test_example.py',
                 'models/tokenizer.json','artifacts/course.txt','docs/evidence/secret.json',
                 'tools/tts-packages/private.py','.venv/private.py','.env','native/build/config.json',
                 'app/web_follow/web/vendor/LICENSE','app/web_follow/extension/content.js',
                 'app/locales/en.json','native/launcher/ui_language.h','README.en.md',
                 'docs/LOCAL_WORKSPACE_README.md','docs/CLEANUP.md','docs/assets/elt-main-en.png',
                 'experiments/lookahead/server.py','experiments/lookahead/tests/test_bridge.py',
                 'experiments/lookahead/extension/manifest.json','experiments/lookahead/.runtime/options.json',
                 'experiments/lookahead/evidence/transcript.md','experiments/lookahead/tests/__pycache__/private.py'):
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('example',encoding='utf-8')
    names={destination.as_posix() for _,destination in module.candidates(tmp_path)}
    assert {'app/main.py','tools/source.py','config/asr.toml','README.md'}<=names
    assert not any(name.startswith(('models/','artifacts/','docs/evidence/','.venv/','native/build/','tools/tts-packages/')) for name in names)
    assert '.env' not in names and not any('__pycache__' in name for name in names)
    assert {'app/web_follow/web/vendor/LICENSE','app/web_follow/extension/content.js',
            'app/locales/en.json','native/launcher/ui_language.h','README.en.md','docs/assets/elt-main-en.png',
            'experiments/lookahead/server.py','experiments/lookahead/tests/test_bridge.py',
            'experiments/lookahead/extension/manifest.json'}<=names
    assert not any(name.startswith(('experiments/lookahead/.runtime/','experiments/lookahead/evidence/')) for name in names)
    assert 'docs/LOCAL_WORKSPACE_README.md' not in names and 'docs/CLEANUP.md' not in names


def test_tts_lock_removes_machine_paths_without_changing_versions():
    text='torch @ file:///example/torch.whl\ntorchaudio @ file:///example/audio.whl\nfaster-qwen3-tts @ file:///example/faster.whl\nnumpy==2.3.5\n'
    result=module.portable_tts_lock(text)
    assert 'file:' not in result
    for pin in ('torch==2.8.0+cu128','torchaudio==2.8.0+cu128','faster-qwen3-tts==0.2.6','numpy==2.3.5'):
        assert pin in result
    with pytest.raises(ValueError):module.portable_tts_lock('unknown @ file:///example/private.whl')


def test_published_checkout_can_be_exported_again_without_a_local_readme(tmp_path):
    (tmp_path/'tools').mkdir();(tmp_path/'docs').mkdir()
    (tmp_path/'README.md').write_text('Published project',encoding='utf-8')
    local=tmp_path/'docs/LOCAL_WORKSPACE_README.md';local.write_text('Original deployment notes',encoding='utf-8')
    files=list(module.candidates(tmp_path));names=[name.as_posix() for _,name in files]
    assert len(names)==len(set(names))
    assert dict((name.as_posix(),source) for source,name in files)['README.md']==tmp_path/'README.md'
    assert 'docs/LOCAL_WORKSPACE_README.md' not in names
