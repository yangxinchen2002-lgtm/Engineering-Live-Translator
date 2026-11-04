"""Build the current source into a clean, independently configured Windows release."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.build_portable import stage,inventory,compress,finish,write_cmd

TAG='v0.1.0-preview.20261104'


def configure(distribution,info):
    tools=distribution/'tools';docs=distribution/'docs';docs.mkdir()
    for name in ('prepare_model.py','setup_gpu.py','download_tts_assets.py','install_tts_runtime.py'):
        shutil.copy2(ROOT/'tools'/name,tools/name)
    for name in ('MODEL_SETUP.md','MODEL_SETUP.en.md'):
        shutil.copy2(ROOT/'docs'/name,docs/name)
    for name in ('Whisper-LICENSE.txt',):
        (tools/'package_licenses').mkdir(exist_ok=True)
        shutil.copy2(ROOT/'tools/package_licenses'/name,tools/'package_licenses'/name)
    scripts={
        'Download-ASR-Model.cmd':'"runtime\\python\\python.exe" -B "tools\\prepare_model.py"',
        'Download-Qwen-0.6B.cmd':'"runtime\\python\\python.exe" -B "tools\\download_tts_assets.py" --only model --model-size 0.6B',
        'Download-Qwen-1.7B.cmd':'"runtime\\python\\python.exe" -B "tools\\download_tts_assets.py" --only model --model-size 1.7B',
        'Install-Qwen-Runtime.cmd':'"runtime\\python\\python.exe" -B "tools\\install_tts_runtime.py"',
    }
    for name,command in scripts.items():
        write_cmd(distribution/name,'@echo off\nsetlocal\ncd /d "%~dp0"\n'+command+'\nif errorlevel 1 goto failed\necho Finished successfully.\npause\nexit /b 0\n:failed\necho Setup failed. Read the error above; no success was reported.\npause\nexit /b 1\n')
    info.update(release_tag=TAG,asr_model_bundled=True,gpu_runtime_bundled=True,
        qwen_model_bundled=False,qwen_runtime_bundled=False,vlc_bundled=False,
        browser_profile_bundled=False)
    (distribution/'distribution.json').write_text(json.dumps(info,indent=2),'utf-8')
    (distribution/'使用说明.txt').write_text(
        'ELT Windows 11 x64 — 中英文便携预览版 / Portable Preview\n\n'
        '双击 ELT.exe。无需另装 Python 或 Visual Studio。不要只复制一个 EXE，完整目录必须保留。\n'
        '首次打开无密钥、个人字幕或课程登录状态。自行在翻译页添加 API Key，选择中文或 English 目标。\n'
        '源语言、界面语言和翻译目标分别设置；界面语言切换后重开软件。\n'
        '基础包含 Whisper 识别模型、GPU 运行库和 Windows 系统音色支持；显卡驱动与 WebView2 由 Windows 提供。\n'
        '使用 Windows 音色时请在朗读模型中选择 Windows 系统音色，无需安装 Qwen。\n'
        'Qwen 朗读为选装：先安装完整 Python 3.12 x64，再运行 Install-Qwen-Runtime.cmd 和模型下载入口。\n'
        '详见 docs/MODEL_SETUP.md，英文版为 docs/MODEL_SETUP.en.md。\n'
        '只需字幕翻译时不用安装任何 Qwen 模型；当前译文由你选择的 API 提供。\n'
        '密钥保存到本机 Windows 凭据库，字幕保存默认关闭。本版独立配置不读取开发版凭据。\n'
        '网页登录资料仅在你首次自行登录后创建，未随包分发。\n'
        'This package starts with no personal keys, transcripts or browser login data. Open ELT.exe.\n'
        'Choose Windows system voices for narration without Qwen, or follow docs/MODEL_SETUP.en.md.\n'
        'This is a preview: a second clean computer and long-duration performance are not certified.\n','utf-8')
    notices=(distribution/'THIRD_PARTY_NOTICES.txt').read_text('utf-8')
    notices='\n'.join(line for line in notices.splitlines() if not line.startswith('VLC '))+'\n'
    notices+='pywebview, pythonnet, WebView2 SDK: license files retained in package metadata.\n'
    (distribution/'THIRD_PARTY_NOTICES.txt').write_text(notices,'utf-8')


def package_notes(packages,groups):
    (packages/'READ-FIRST.txt').write_text(
        'ELT Windows 11 x64 — Portable Preview\n\n'
        '1. Download ALL 01-ELT-Core, 02-ASR-Model and 03-GPU-Runtime volumes.\n'
        '2. Also download 7za.exe, Extract-ELT.cmd, SHA256SUMS.txt and packages.json. Keep them together.\n'
        '3. Double-click Extract-ELT.cmd. It checks and extracts the three archive groups.\n'
        '4. Open the ELT folder and double-click ELT.exe. Do not launch the source-code ZIP.\n'
        '5. Add your own API key. Use Windows voices, or follow the optional Qwen setup guide.\n\n'
        '每个文件均不超过 400 MB。所有分卷与 7za.exe / Extract-ELT.cmd 放在同一个文件夹。\n'
        '双击 Extract-ELT.cmd；完成后进入 ELT，双击 ELT.exe。后续 .002 等分卷不可单独解压或改名。\n'
        '01=主程序；02=Whisper 识别模型；03=GPU 运行库。三组均为基础识别所需。\n'
        'Qwen 仅用于可选的本地朗读，教程：MODEL_SETUP.md / MODEL_SETUP.en.md。\n'
        '不含个人密钥、字幕或课程登录信息；首次自己配置。\n','utf-8')
    # Keep the existing extractor's CRC checks and no-overwrite behavior.
    shutil.copy2(packages/'一键解压.cmd',packages/'Extract-ELT.cmd')
    # GitHub normalizes non-ASCII asset names; retain the canonical ASCII copy.
    (packages/'一键解压.cmd').unlink()
    for name in ('MODEL_SETUP.md','MODEL_SETUP.en.md'):
        shutil.copy2(ROOT/'docs'/name,packages/name)
    (packages/'先读我-解压与启动.txt').unlink(missing_ok=True)
    manifest=json.loads((packages/'packages.json').read_text('utf-8'))
    manifest.update(release_tag=TAG,groups=groups,source_only=False)
    (packages/'packages.json').write_text(json.dumps(manifest,indent=2),'utf-8')
    sums=[]
    for path in sorted(packages.iterdir()):
        if path.name=='SHA256SUMS.txt':continue
        if not path.is_file() or path.stat().st_size>400_000_000:raise ValueError('oversized release asset')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        sums.append(f'{digest}  {path.name}\n')
    (packages/'SHA256SUMS.txt').write_text(''.join(sums),'utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--sevenzip',type=Path,required=True)
    parser.add_argument('--python-base',type=Path,default=Path(sys.base_prefix));args=parser.parse_args()
    output=args.output.resolve();sevenzip=args.sevenzip.resolve()
    if not output.is_relative_to(ROOT/'dist') or output==ROOT/'dist' or output.exists():parser.error('Choose a fresh child directory inside dist/.')
    if not sevenzip.is_file():parser.error('7-Zip executable missing.')
    output.mkdir(parents=True)
    distribution,info=stage(output,args.python_base.resolve(),include_vlc=False)
    configure(distribution,info)
    print(json.dumps({'event':'staged','profile':info['profile'],'release_tag':TAG}),flush=True)
    records=inventory(distribution,progress=True)
    (distribution/'files.manifest.json').write_text(json.dumps({'format':1,'files':records},ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'event':'audited','files':len(records),'bytes':sum(r['bytes'] for r in records)}),flush=True)
    packages,groups=compress(output,distribution,sevenzip)
    finish(output,packages,groups,sevenzip);package_notes(packages,groups)
    print(json.dumps({'event':'release_prepared','groups':groups,'assets':len(list(packages.iterdir())),'directory':str(packages)}),flush=True)


if __name__=='__main__':main()
