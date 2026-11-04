from pathlib import Path
import pytest
from tools.build_portable import allowed,copy_tree,inventory,VOLUME_BYTES


@pytest.mark.parametrize('name',['.env','.env.local','ui-settings.json','saved.jsonl','session.srt',
    'recording.wav','db.sqlite3','direct_url.json','__editable__.project.pth','__pycache__/a.pyc','win32com/gen_py/cache.py'])
def test_personal_state_caches_and_editable_paths_are_excluded(name):
    assert not allowed(Path(name))


def test_copy_includes_real_runtime_assets_and_licenses_but_no_saved_state(tmp_path):
    source=tmp_path/'source';source.mkdir();dest=tmp_path/'dest'
    for name in ('model.bin','LICENSE.txt','public.py','.env','subtitle.jsonl'):(source/name).write_text('public data',encoding='utf-8')
    (source/'__pycache__').mkdir();(source/'__pycache__/local.pyc').write_bytes(b'private path')
    copy_tree(source,dest)
    assert {p.name for p in dest.iterdir()}=={'model.bin','LICENSE.txt','public.py'}
    assert len(inventory(dest))==3 and VOLUME_BYTES<400_000_000


def test_plaintext_credential_like_material_is_rejected_without_printing_value(tmp_path):
    sentinel='sk-'+'testonly'*6;(tmp_path/'config.json').write_text('{"key":"'+sentinel+'"}',encoding='utf-8')
    with pytest.raises(ValueError) as caught:inventory(tmp_path)
    assert sentinel not in str(caught.value) and 'config.json' in str(caught.value)
