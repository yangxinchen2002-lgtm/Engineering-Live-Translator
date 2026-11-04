"""Read publisher metadata only; no model/runtime execution or API credentials."""
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


def fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':'ELT-local-model-preparation'})
    with urllib.request.urlopen(request,timeout=40) as response:return response.read(4*1024*1024)


if __name__=='__main__':
    model=json.loads(fetch('https://huggingface.co/api/models/unsloth/Qwen3-4B-Instruct-2507-GGUF?blobs=true'))
    stable=json.loads(fetch('https://api.github.com/repos/ggml-org/llama.cpp/releases/latest'))
    tag=fetch(next(asset['browser_download_url'] for asset in stable['assets'] if asset['name']=='nightly-tag.txt')).decode().strip()
    release=json.loads(fetch(f'https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/{tag}'))
    result={'model_repo':model['id'],'model_revision':model['sha'],
            'model_files':[file for file in model['siblings'] if file['rfilename'].endswith('Q4_K_M.gguf')],
            'runtime_release':release['tag_name'],'stable_release':stable['tag_name'],
            'runtime_commit':release['target_commitish'],
            'runtime_assets':[{key:asset.get(key) for key in ('name','size','digest','browser_download_url')}
                for asset in release['assets'] if 'win-cuda-12.4-x64' in asset['name']]}
    path=ROOT/'docs/evidence/local-translation-assets.json';path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
