"""Export an explicit source allowlist, scan credentials, and omit all local run data."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES=('.gitignore','.gitattributes','.env.example','pyproject.toml','启动ELT.cmd','README.en.md',
            'requirements-m1-lock.txt','requirements-m2-lock.txt','requirements-ui-lock.txt','requirements-tts-lock.txt')
TEXT_SUFFIXES={'.py','.toml','.json','.md','.txt','.ps1','.html','.css','.js','.mjs','.cpp','.h','.rc','.svg','.cmd'}
SECRETS=re.compile(r'sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----')


def candidates(root):
    for name in ROOT_FILES:yield root/name,Path(name)
    for folder,suffixes in [('app',{'.py','.json','.svg','.ico','.png','.js','.mjs','.html','.css','.md','.txt'}),('config',{'.toml'}),('terminology',{'.json'}),
                            ('tests/unit',{'.py','.mjs'}),('tests/integration',{'.py'}),
                            ('native/audio_capture',{'.cpp','.h'}),('native/launcher',{'.cpp','.h','.txt','.rc','.ico'})]:
        for source in sorted((root/folder).rglob('*')):
            if '__pycache__' in source.parts or not source.is_file():continue
            if source.suffix in suffixes or (folder=='app' and source.name=='LICENSE'):yield source,source.relative_to(root)
    for source in sorted((root/'tools').iterdir()):
        if source.is_file() and source.suffix in {'.py','.ps1','.html'}:yield source,source.relative_to(root)
    for source in sorted((root/'docs').glob('*.md')):
        if source.name not in {'CLEANUP.md','LOCAL_WORKSPACE_README.md'}:yield source,source.relative_to(root)
    for source in sorted((root/'docs/assets').glob('*')):
        if source.is_file() and source.suffix in {'.png','.svg'}:yield source,source.relative_to(root)
    # Only compatibility sources and tests, never experiment runtime/evidence.
    legacy=root/'experiments/lookahead'
    for name in ('__init__.py','bridge.py','hls.py','media.py','sentences.py','server.py','speech.py',
                 'timeline.py','worker.py','打开视频预读实验.pyw','README.md'):
        source=legacy/name
        if source.is_file():yield source,source.relative_to(root)
    for folder in ('extension','tests'):
        for source in sorted((legacy/folder).rglob('*')):
            if '__pycache__' not in source.parts and source.is_file() and source.suffix in {'.py','.mjs','.js','.html','.css','.json','.md','.png','.svg'}:
                yield source,source.relative_to(root)
    for name in ('native/CMakeLists.txt','tests/fixtures/m2_engineering_sentences.json','tools/package_licenses/Whisper-LICENSE.txt'):
        yield root/name,Path(name)
    published_readme=root/'README.github.md'
    yield published_readme if published_readme.exists() else root/'README.md',Path('README.md')


def portable_tts_lock(text):
    versions={'faster-qwen3-tts':'0.2.6','torch':'2.8.0+cu128','torchaudio':'2.8.0+cu128'}
    lines=['# Windows x64 / Python 3.12. Separate TTS environment. No machine-local wheel paths.',
           '--extra-index-url https://download.pytorch.org/whl/cu128']
    for line in text.splitlines():
        if ' @ file:' in line:
            name=line.split(' @ ',1)[0]
            if name not in versions:raise ValueError('unexpected local dependency reference')
            line=f'{name}=={versions[name]}'
        lines.append(line)
    return '\n'.join(lines)+'\n'


def export(root,output):
    root=root.resolve();output=output.resolve()
    if not output.is_relative_to(root) or output==root:raise ValueError('choose a new subdirectory inside the project')
    output.mkdir(parents=True,exist_ok=False);records=[];seen=set()
    for source,relative in candidates(root):
        if relative in seen:raise ValueError(f'duplicate source destination: {relative}')
        seen.add(relative)
        if source.is_symlink() or any(p.is_junction() for p in source.parents if p.is_relative_to(root)):
            raise ValueError('reparse points are excluded from source exports')
        raw=source.read_bytes()
        if len(raw)>2*1024*1024:raise ValueError(f'oversized source file: {relative}')
        if source.suffix in TEXT_SUFFIXES or source.name in ROOT_FILES:
            text=raw.decode('utf-8-sig')
            if SECRETS.search(text):raise ValueError(f'possible credential in {relative}; export stopped')
            if relative.name=='requirements-tts-lock.txt':raw=portable_tts_lock(text).encode('utf-8')
        target=output/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        records.append({'path':relative.as_posix(),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
    manifest={'format':1,'purpose':'source-only GitHub export','files':records,
              'excluded':['models','environments','compiled binaries','course media','transcripts','credentials','logs','raw run artifacts']}
    (output/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive=output.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as bundle:
        for source in sorted(output.rglob('*')):
            if source.is_file():bundle.write(source,source.relative_to(output).as_posix())
    return {'directory':str(output),'archive':str(archive),'files':len(records)+1,'source_bytes':sum(r['bytes'] for r in records),
            'archive_bytes':archive.stat().st_size,'archive_sha256':hashlib.file_digest(archive.open('rb'),'sha256').hexdigest()}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(export(ROOT,args.output),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
