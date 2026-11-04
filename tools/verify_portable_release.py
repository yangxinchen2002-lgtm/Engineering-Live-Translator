"""Verify every volume, extract to a fresh path, then check the relocated runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--release',type=Path,required=True)
    args=parser.parse_args();release=args.release.resolve();project=Path(__file__).resolve().parents[1]
    if not release.is_relative_to(project/'dist'):parser.error('release must be inside project dist/')
    packages=release/'packages';manifest=json.loads((packages/'packages.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path=(packages/item['file']).resolve()
        if path.parent!=packages or not 0<path.stat().st_size<=400_000_000:raise ValueError('invalid release volume')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=item['sha256']:raise ValueError('release volume checksum mismatch: '+path.name)
    for path in packages.iterdir():
        if not path.is_file() or path.stat().st_size>400_000_000:raise ValueError('unexpected oversized/non-file delivery entry')
    destination=release/'verification'/'relocated-path';destination.mkdir(parents=True,exist_ok=False)
    logs=release/'verification-logs';logs.mkdir()
    groups=sorted(packages.glob('*.7z.001'))
    if len(groups)!=4:raise ValueError('expected four runtime groups')
    for archive in groups:
        print(json.dumps({'phase':'extract','archive':archive.name}),flush=True)
        # Extraction also verifies archive CRCs, including all subsequent volumes.
        with (logs/(archive.name+'.txt')).open('wb') as log:
            subprocess.run([str(packages/'7za.exe'),'x',str(archive),'-o'+str(destination),'-aos','-bsp0'],
                           stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900)
    root=destination/'ELT';profile=json.loads((root/'distribution.json').read_text(encoding='utf-8'))['profile']
    environment=os.environ.copy();environment['ELT_PROFILE_ID']=profile
    environment.pop('DEEPSEEK_API_KEY',None);environment['HF_HUB_OFFLINE']='1'
    environment['PATH']=str(Path(os.environ['SystemRoot'])/'System32')+os.pathsep+os.environ['SystemRoot']
    python=root/'runtime/python/python.exe'
    with (logs/'relocated-check.txt').open('wb') as log:
        subprocess.run([str(python),'-B',str(root/'tools/check_portable.py')],cwd=destination,
                       env=environment,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
    with (logs/'cli-help.txt').open('wb') as log:
        subprocess.run([str(python),'-B','-m','app.main','--help'],cwd=destination,
                       env=environment,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)
    metadata=json.loads((root/'files.manifest.json').read_text(encoding='utf-8'))
    report={'verified':True,'volume_count':len(manifest['files']),'group_count':len(groups),
            'compressed_bytes':sum(i['bytes'] for i in manifest['files']),
            'largest_volume_bytes':max(i['bytes'] for i in manifest['files']),
            'all_delivery_files_below_400MB':True,'extracted_files_verified':len(metadata['files']),
            'relocated_isolated_runtime_checked':True,'paid_api_calls':0,'audio_capture_tests':False,
            'clean_second_pc_test':False}
    (release/'verification-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
