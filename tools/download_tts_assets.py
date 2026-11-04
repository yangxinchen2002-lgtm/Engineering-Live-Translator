"""Verified, resumable range downloads from official PyTorch/Hugging Face hosts."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import time
from urllib.parse import unquote, urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
REVISION = '85e237c12c027371202489a0ec509ded67b5e4b5'
REPO = 'Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice'
MODELS = {
    '0.6B': (REPO, REVISION),
    '1.7B': ('Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice', '0c0e3051f131929182e2c023b9537f8b1c68adfe'),
}
CHUNK = 8 * 1024 * 1024


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            digest.update(block)
    return digest.hexdigest()


def download(client, url, destination, size, digest,workers=24):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.stat().st_size == size and sha256(destination) == digest:
        print(f'Already verified: {destination.name}', flush=True)
        return
    parts = ROOT/'.tmp/tts-download'/(destination.name+'-'+digest[:12])
    parts.mkdir(parents=True, exist_ok=True)
    count = (size+CHUNK-1)//CHUNK
    def part(index):
        start, end = index*CHUNK, min((index+1)*CHUNK, size)-1
        path = parts/f'{index:05d}.part'
        if path.exists() and path.stat().st_size == end-start+1:
            return
        last = None
        for attempt in range(5):
            try:
                # Distinct cache keys also protect against intermediaries caching a different Range.
                request_url = url+('&' if '?' in url else '?')+f'elt_part={index}'
                with client.stream('GET', request_url, headers={'Range': f'bytes={start}-{end}'}) as response:
                    response.raise_for_status()
                    expected = f'bytes {start}-{end}/{size}'
                    if response.status_code != 206 or response.headers.get('content-range') != expected:
                        raise RuntimeError(f'unexpected range: {response.status_code} {response.headers.get("content-range")}')
                    temporary = path.with_suffix('.partial')
                    with temporary.open('wb') as output:
                        for block in response.iter_bytes(256*1024):
                            output.write(block)
                    if temporary.stat().st_size != end-start+1:
                        raise RuntimeError('incomplete range')
                    temporary.replace(path)
                return
            except Exception as error:
                last = error
                time.sleep(min(attempt+1, 4))
        raise RuntimeError(f'part {index} failed: {last}')
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = [pool.submit(part, i) for i in range(count)]
        for completed, future in enumerate(as_completed(pending), 1):
            future.result()
            if completed % 8 == 0 or completed == count:
                print(json.dumps({'file': destination.name, 'parts': completed, 'total_parts': count,
                                  'elapsed_s': round(time.perf_counter()-started, 1)}), flush=True)
    temporary = destination.with_suffix(destination.suffix+'.assembling')
    with temporary.open('wb') as output:
        for index in range(count):
            with (parts/f'{index:05d}.part').open('rb') as source:
                for block in iter(lambda: source.read(CHUNK), b''):
                    output.write(block)
    actual = sha256(temporary)
    if actual != digest or temporary.stat().st_size != size:
        raise RuntimeError(f'checksum mismatch: {destination.name}')
    temporary.replace(destination)
    print(json.dumps({'verified': str(destination), 'size': size, 'sha256': actual}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=['all','torch','model'], default='all')
    parser.add_argument('--model-size', choices=tuple(MODELS), default='0.6B')
    parser.add_argument('--workers',type=int,default=24)
    args = parser.parse_args()
    if not 1<=args.workers<=64:parser.error('workers must be between 1 and 64')
    repo, revision = MODELS[args.model_size]
    target = ROOT/'models'/repo.split('/')[1]
    with httpx.Client(trust_env=False, follow_redirects=True, timeout=httpx.Timeout(90, connect=20),
                      limits=httpx.Limits(max_connections=args.workers+4, max_keepalive_connections=args.workers+4)) as client:
        if args.only in ('all', 'torch'):
            index = client.get('https://download.pytorch.org/whl/cu128/torch/').raise_for_status().text
            links = [html.unescape(x) for x in re.findall(r'href="([^"]+)"', index)]
            wheel_name = 'torch-2.8.0+cu128-cp312-cp312-win_amd64.whl'
            link = next(x for x in links if unquote(urlsplit(x).path).endswith('/'+wheel_name))
            digest = urlsplit(link).fragment.split('sha256=')[1]
            url = link.split('#')[0]
            download(client, url, ROOT/'tools/tts-packages'/wheel_name, 3461384651, digest,args.workers)
        if args.only == 'torch':
            return
        metadata = client.get(f'https://huggingface.co/api/models/{repo}/revision/{revision}',
                              params={'blobs': 'true'}).raise_for_status().json()
        manifest = {'repo': repo, 'revision': revision, 'files': []}
        for item in metadata['siblings']:
            path = target/item['rfilename']
            url = f'https://huggingface.co/{repo}/resolve/{revision}/{item["rfilename"]}'
            if item.get('lfs'):
                if not path.exists():
                    for sibling_repo,_ in MODELS.values():
                        existing=ROOT/'models'/sibling_repo.split('/')[1]/item['rfilename']
                        if existing==path or not existing.is_file() or existing.stat().st_size!=item['size']:continue
                        if sha256(existing)!=item['lfs']['sha256']:continue
                        path.parent.mkdir(parents=True,exist_ok=True)
                        temporary=path.with_suffix(path.suffix+'.reusing');shutil.copyfile(existing,temporary);temporary.replace(path)
                        print('Reusing verified local file: '+item['rfilename'],flush=True);break
                download(client, url, path, item['size'], item['lfs']['sha256'],args.workers)
            elif not path.exists():
                response = client.get(url).raise_for_status()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(response.content)
            if path.stat().st_size != item['size']:
                raise RuntimeError('size mismatch: '+item['rfilename'])
            if not item.get('lfs'):
                contents = path.read_bytes()
                git_hash = hashlib.sha1(b'blob '+str(len(contents)).encode()+b'\0'+contents).hexdigest()
                if git_hash != item['blobId']:
                    raise RuntimeError('git blob checksum mismatch: '+item['rfilename'])
            manifest['files'].append({'path': item['rfilename'], 'size': path.stat().st_size,
                                      'sha256': sha256(path)})
        (target/'elt-manifest.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        print('ALL ASSETS VERIFIED', flush=True)


if __name__ == '__main__':
    main()
