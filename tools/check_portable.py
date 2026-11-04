"""Read-only distribution check. Does not capture audio, read a key, or call DeepSeek."""
from pathlib import Path
import hashlib
import importlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    if sys.flags.isolated!=1:raise RuntimeError('use the bundled isolated Python runtime')
    manifest=json.loads((ROOT/'files.manifest.json').read_text(encoding='utf-8'))
    for record in manifest['files']:
        path=(ROOT/record['path']).resolve()
        if not path.is_relative_to(ROOT):raise ValueError('invalid manifest path')
        if path.stat().st_size!=record['bytes']:raise ValueError('size mismatch: '+record['path'])
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=record['sha256']:raise ValueError('hash mismatch: '+record['path'])
    for name in ('numpy','scipy.signal','av','onnxruntime','ctranslate2','faster_whisper','PySide6.QtWidgets',
                 'PySide6.QtSvg','win32cred','win32job','httpx','app.ui.main'):
        module=importlib.import_module(name)
        file=getattr(module,'__file__',None)
        if file and not Path(file).resolve().is_relative_to(ROOT):raise RuntimeError('module loaded outside distribution: '+name)
    from app.ui.preferences import default_path,PreferencesStore
    from app.translation.credentials import credential_target
    profile=json.loads((ROOT/'distribution.json').read_text(encoding='utf-8'))['profile']
    if profile not in credential_target() or profile not in str(default_path()):raise RuntimeError('distribution profile not selected')
    result={'files_verified':len(manifest['files']),'python':sys.version.split()[0],
            'isolated':sys.flags.isolated,'all_modules_local':True,'credential_profile_isolated':True,
            'model_present':(ROOT/'models/large-v3-turbo/model.bin').is_file(),
            'history_saving_default':PreferencesStore(ROOT/'nonexistent-default-settings.json').load().save_transcripts}
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
