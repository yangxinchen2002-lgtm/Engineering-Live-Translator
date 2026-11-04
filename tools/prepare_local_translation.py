"""Explicit, pinned local Qwen GGUF / llama.cpp download; no inference or credentials."""
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
MODEL_NAME='Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
MODEL_REVISION='a06e946bb6b655725eafa393f4a9745d460374c9'
MODEL_SHA256='3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597'
VERSION='b11960'
PACKAGES=[
    (f'https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/{MODEL_REVISION}/{MODEL_NAME}',
     ROOT/'models'/MODEL_NAME,2497281120,MODEL_SHA256),
    (f'https://github.com/ggml-org/llama.cpp/releases/download/{VERSION}/llama-{VERSION}-bin-win-cuda-12.4-x64.zip',
     ROOT/f'tools/downloads/llama-{VERSION}-bin-win-cuda-12.4-x64.zip',279763224,
     '8d9d819261de10cc2f03921b8b79c779c5c458e21edb60c170ee30a7d462d684'),
    (f'https://github.com/ggml-org/llama.cpp/releases/download/{VERSION}/cudart-llama-bin-win-cuda-12.4-x64.zip',
     ROOT/'tools/downloads/cudart-llama-bin-win-cuda-12.4-x64.zip',391443627,
     '8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6'),
]


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def ranged_download(url,path,size,sha256):
    """Verified HTTP ranges; a .part file is never treated as an installed model."""
    curl=shutil.which('curl.exe') or shutil.which('curl')
    if not curl:raise RuntimeError('curl is required for bounded ranged downloads')
    partial=path.with_suffix(path.suffix+'.part');state_path=path.with_suffix(path.suffix+'.ranges.json')
    chunks=path.parent/(path.name+'.chunks');chunks.mkdir(exist_ok=True)
    chunk_size=8*1024*1024;state={'sha256':sha256,'size':size,'chunk_size':chunk_size,'done':[]}
    if state_path.exists():
        candidate=json.loads(state_path.read_text(encoding='utf-8'))
        if all(candidate.get(key)==state[key] for key in ('sha256','size','chunk_size')) and partial.exists() and partial.stat().st_size==size:state=candidate
    with partial.open('r+b' if partial.exists() else 'w+b') as output:output.truncate(size)
    def part(index):
        start=index*chunk_size;end=min(size,start+chunk_size)-1;destination=chunks/f'{index}.part'
        result=subprocess.run([curl,'--disable','--location','--fail','--silent','--show-error','--retry','2',
            '--connect-timeout','15','--max-time','90','--proto','=https','--proto-redir','=https',
            '--range',f'{start}-{end}','--max-filesize',str(end-start+1),'--dump-header','-',
            '--output',str(destination),url],capture_output=True,timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        ranges=re.findall(rb'(?im)^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)',result.stdout)
        if result.returncode or not ranges or tuple(map(int,ranges[-1]))!=(start,end,size):raise RuntimeError(f'range download failed: {path.name} chunk {index}, curl={result.returncode}')
        if destination.stat().st_size!=end-start+1:raise RuntimeError('range length mismatch')
        return index,destination
    total=(size+chunk_size-1)//chunk_size;done=set(state['done'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(part,index) for index in range(total) if index not in done]
        with partial.open('r+b') as output:
            for future in as_completed(futures):
                index,destination=future.result();output.seek(index*chunk_size);output.write(destination.read_bytes());output.flush()
                done.add(index);state['done']=sorted(done)
                temporary=state_path.with_suffix('.tmp');temporary.write_text(json.dumps(state),encoding='utf-8');temporary.replace(state_path)
                destination.unlink()
                print(json.dumps({'download':path.name,'completed_chunks':len(done),'total_chunks':total}),flush=True)
    if partial.stat().st_size!=size or digest(partial)!=sha256:raise RuntimeError(f'download SHA256 mismatch: {path.name}')
    partial.replace(path)


def download(spec):
    url,path,size,sha256=spec;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.stat().st_size!=size or digest(path)!=sha256:raise RuntimeError(f'existing file is not the pinned artifact: {path.name}')
    else:
        ranged_download(url,path,size,sha256)
    print(json.dumps({'verified':path.name,'size':size,'sha256':sha256}),flush=True)
    return {'url':url,'path':str(path.relative_to(ROOT)),'size':size,'sha256':sha256}


def main():
    with ThreadPoolExecutor(max_workers=3) as pool:artifacts=list(pool.map(download,PACKAGES))
    destination=ROOT/f'tools/llama-{VERSION}';destination.mkdir(parents=True,exist_ok=True)
    for spec in PACKAGES[1:]:
        with zipfile.ZipFile(spec[1]) as archive:
            for info in archive.infolist():
                if not (destination/info.filename).resolve().is_relative_to(destination.resolve()):raise RuntimeError('unsafe archive path')
            archive.extractall(destination)
    executables=list(destination.rglob('llama-server.exe'))
    if len(executables)!=1:raise RuntimeError('expected one llama-server.exe')
    manifest={'version':1,'runtime_version':VERSION,'runtime_commit':'8642541b255bfb5dc39cd351a178be09013a55d6',
        'model_repo':'unsloth/Qwen3-4B-Instruct-2507-GGUF','model_revision':MODEL_REVISION,
        'model_path':str(PACKAGES[0][1].relative_to(ROOT)),'server_path':str(executables[0].relative_to(ROOT)),
        'artifacts':artifacts}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'prepared':True,'manifest':str(destination/'manifest.json'),'inference_tested':False}),flush=True)


if __name__=='__main__':main()
