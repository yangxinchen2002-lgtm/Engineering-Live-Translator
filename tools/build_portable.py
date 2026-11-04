"""Build an allowlisted, personal-data-free Windows distribution in fresh dist/ output."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
VOLUME_BYTES=390_000_000  # Below both 400 MB (decimal) and 400 MiB.
EXCLUDED_DIRS={'__pycache__','.cache','tests','test','examples','demos','.pytest_cache','gen_py',
               '.runtime','course-browser','browser-profile','profiles','gpucache','shadercache','local storage'}
EXCLUDED_SUFFIXES={'.pyc','.pyo','.log','.jsonl','.srt','.vtt','.wav','.mp3','.mp4','.m4a','.webm','.mkv','.flac',
                   '.sqlite','.sqlite3','.bak','.tmp'}


def allowed(relative:Path) -> bool:
    if any(p.lower() in EXCLUDED_DIRS for p in relative.parts):return False
    name=relative.name.lower()
    if name.startswith(('.env','__editable__')) or name in ('direct_url.json','ui-settings.json','pyvenv.cfg','sitecustomize.py','usercustomize.py',
        'cookies','login data','web data','history','preferences','local state'):
        return False
    if 'engineering_live_translator' in name and name.endswith(('.dist-info','.egg-info')):return False
    return relative.suffix.lower() not in EXCLUDED_SUFFIXES


def copy_tree(source:Path,destination:Path,*,exclude=()):
    if not source.is_dir():raise FileNotFoundError(f'required directory absent: {source.name}')
    for current,dirs,files in os.walk(source,followlinks=False):
        relative=Path(current).relative_to(source)
        dirs[:]=[d for d in dirs if allowed(relative/d) and not (relative==Path('.') and d in exclude)]
        for d in dirs:
            if (Path(current)/d).is_junction() or (Path(current)/d).is_symlink():raise ValueError('reparse directory not allowed in distribution')
        for name in files:
            item=relative/name
            if not allowed(item):continue
            original=Path(current)/name
            if original.is_symlink():raise ValueError('symlink not allowed in distribution')
            target=destination/item;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)


def write_cmd(path:Path,text:str):
    path.write_bytes(text.replace('\r\n','\n').replace('\n','\r\n').encode('ascii'))


def stage(output:Path,python_base:Path,*,include_vlc=True):
    distribution=output/'staging'/'ELT';distribution.mkdir(parents=True)
    profile='portable-'+uuid.uuid4().hex
    copy_tree(ROOT/'app',distribution/'app')
    (distribution/'config').mkdir()
    for name in ('asr.toml','translation.toml'):shutil.copy2(ROOT/'config'/name,distribution/'config'/name)
    copy_tree(ROOT/'terminology',distribution/'terminology')
    for name in ('pyproject.toml','requirements-m1-lock.txt','requirements-m2-lock.txt','requirements-ui-lock.txt','requirements-tts-lock.txt'):
        shutil.copy2(ROOT/name,distribution/name)
    python=distribution/'runtime/python';python.mkdir(parents=True)
    for name in ('python.exe','pythonw.exe','python3.dll','python312.dll','LICENSE.txt'):
        shutil.copy2(python_base/name,python/name)
    copy_tree(python_base/'DLLs',python/'DLLs')
    copy_tree(python_base/'Lib',python/'Lib',exclude=('site-packages','idlelib','turtledemo','ensurepip'))
    copy_tree(ROOT/'.venv/Lib/site-packages',python/'Lib/site-packages')
    # Relative paths, isolated mode, no system/user site or editable development checkout.
    # CPython 3.12.10 on Windows normalizes a final forward-slash ../.. to
    # only one parent; native separators keep the root correct after relocation.
    (python/'python312._pth').write_text('.\nDLLs\nLib\nLib\\site-packages\n..\\..\nimport site\n',encoding='ascii')
    crt_roots=list((ROOT/'tools/buildtools/VC/Redist/MSVC').glob('*/x64/Microsoft.VC143.CRT'))
    if not crt_roots:raise FileNotFoundError('MSVC app-local redistributable runtime absent')
    crt=sorted(crt_roots)[-1]
    native=distribution/'native/build/Release';native.mkdir(parents=True)
    shutil.copy2(ROOT/'native/build/Release/elt_capture.exe',native/'elt_capture.exe')
    for dll in crt.glob('*.dll'):
        shutil.copy2(dll,python/dll.name);shutil.copy2(dll,native/dll.name)
    # Keep native sources; no build databases, debug symbols or machine paths.
    copy_tree(ROOT/'native/audio_capture',distribution/'native/audio_capture')
    shutil.copy2(ROOT/'native/CMakeLists.txt',distribution/'native/CMakeLists.txt')
    copy_tree(ROOT/'models/large-v3-turbo',distribution/'models/large-v3-turbo')
    gpu=distribution/'tools/gpu-runtime';gpu.mkdir(parents=True)
    for component in (ROOT/'tools/gpu-runtime').iterdir():
        if component.is_dir():
            for source in component.rglob('*'):
                if source.is_file() and (source.suffix.lower()=='.dll' or source.name.lower() in ('license','license.txt','eula.txt')):
                    target=gpu/source.relative_to(ROOT/'tools/gpu-runtime');target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        elif component.name=='manifest.json':shutil.copy2(component,gpu/component.name)
    if include_vlc:copy_tree(ROOT/'tools/vlc-3.0.24',distribution/'tools/vlc-3.0.24')
    shutil.copy2(ROOT/'tools/check_portable.py',distribution/'tools/check_portable.py')
    if not (ROOT/'ELT.exe').is_file():raise FileNotFoundError('build the native ELT.exe launcher first with tools/build_launcher.py')
    shutil.copy2(ROOT/'ELT.exe',distribution/'ELT.exe')
    shutil.copy2(ROOT/'ELT.exe',distribution/'创建桌面快捷方式.exe')
    info={'format':1,'created_utc':datetime.now(timezone.utc).isoformat(),'profile':profile,'version':'0.1.0',
          'personal_data_included':False,'python_version':'3.12.10','asr_model':'large-v3-turbo'}
    (distribution/'distribution.json').write_text(json.dumps(info,indent=2),encoding='utf-8')
    environment=f'set "ELT_PROFILE_ID={profile}"\nset "DEEPSEEK_API_KEY="\nset "HF_HUB_OFFLINE=1"\n'
    write_cmd(distribution/'启动ELT.cmd','@echo off\nsetlocal\ncd /d "%~dp0"\n'+environment+
        '"%~dp0runtime\\python\\python.exe" -B -c "import PySide6; import app.ui.main"\n'+
        'if errorlevel 1 goto failed\nstart "" "%~dp0runtime\\python\\pythonw.exe" -B -m app.ui.main\n'+
        'if errorlevel 1 goto failed\nexit /b 0\n:failed\necho ELT could not start. Run Check-ELT.cmd for details.\npause\nexit /b 1\n')
    write_cmd(distribution/'Check-ELT.cmd','@echo off\nsetlocal\ncd /d "%~dp0"\n'+environment+
        '"%~dp0runtime\\python\\python.exe" -B "tools\\check_portable.py"\npause\n')
    (distribution/'使用说明.txt').write_text(
        'Engineering Live Translator — Windows 11 x64 便携版\n\n'
        '双击 ELT.exe。需要桌面图标时，双击“创建桌面快捷方式.exe”。无需另装 Python、Visual Studio 或虚拟声卡。\n'
        '首次打开没有 API Key、字幕历史或个人设置。中文翻译需自己设置 DeepSeek 密钥并主动启用。\n'
        '本分发版使用独立的 Windows 凭据名称和设置目录，不读取原开发版密钥，也不继承 DEEPSEEK_API_KEY。\n'
        '密钥仍只存 Windows 用户凭据，不写进软件文件夹。字幕稿默认不保存，启用时自行选目录。\n\n'
        '在 VLC 或 Chrome/Edge 打开视频并暂停，选音源和语言，开始字幕，音频就绪后继续播放。\n'
        'GPU 识别需要支持 CUDA 12 的 NVIDIA 显卡及兼容驱动，建议使用已验证的目标设备。\n'
        'Python、界面依赖、large-v3-turbo、CUDA 12.4/cuDNN 9.1、VLC 已随包提供。\n'
        '显卡驱动与 Windows 系统组件由电脑自身提供；不会替你安装或修改驱动。\n'
        'Qwen 本地翻译部署仍延后，未把无用模型或开发工具放入运行包。\n'
        'Check-ELT.cmd 可检查导入、文件完整性和独立路径，不会发翻译请求或启动捕获。\n\n'
        '此包保留现有功能，完整 M3 的长测/混合 DPI/全屏/质量验收仍待执行。\n'
        '第三方许可保留在 runtime/python/Lib/site-packages 各包、VLC 和 GPU 组件内。\n',encoding='utf-8')
    (distribution/'THIRD_PARTY_NOTICES.txt').write_text(
        'Unmodified third-party runtimes are distributed with their original license files.\n'
        'Python 3.12.10: PSF license, runtime/python/LICENSE.txt; https://www.python.org/\n'
        'PySide6/Qt 6.8.3: bundled license metadata; https://code.qt.io/ and https://pypi.org/project/PySide6/6.8.3/\n'
        'VLC 3.0.24: tools/vlc-3.0.24/COPYING.txt; https://www.videolan.org/vlc/download-sources.html\n'
        'Faster-Whisper 1.2.1: MIT; https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1\n'
        'ASR model: MIT; https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo/tree/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf\n'
        'NVIDIA CUDA 12.4 / cuDNN 9.1: original LICENSE in each tools/gpu-runtime component.\n'
        'MSVC 14.44 app-local CRT: Microsoft redistribution terms; https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files\n'
        'Other Python package licenses remain in their package and dist-info directories.\n',encoding='utf-8')
    return distribution,info


def inventory(distribution:Path,*,progress=False):
    files=[];findings=[]
    forbidden=(str(ROOT).encode(),str(ROOT).replace('\\','/').encode(),
               str(Path.home()).encode(),str(Path.home()).replace('\\','/').encode())
    for path in sorted(distribution.rglob('*')):
        if not path.is_file():continue
        relative=path.relative_to(distribution)
        if not allowed(relative):raise ValueError(f'forbidden distribution entry: {relative.as_posix()}')
        if path.suffix.lower() in ('.py','.json','.toml','.pth','.cmd','.cfg','.txt','.md') and path.stat().st_size<5_000_000:
            raw=path.read_bytes()
            if any(value in raw for value in forbidden):findings.append(relative.as_posix())
            if re.search(rb'(?<![A-Za-z0-9_])(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_-]{30,})',raw):
                findings.append(relative.as_posix())
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        files.append({'path':relative.as_posix(),'bytes':path.stat().st_size,'sha256':digest})
        if progress and len(files)%500==0:print(json.dumps({'event':'audit_progress','files':len(files),'last':relative.as_posix()}),flush=True)
    if findings:raise ValueError('personal path or credential-like material found in: '+', '.join(sorted(set(findings))))
    return files


def compress(output:Path,distribution:Path,sevenzip:Path):
    packages=output/'packages';packages.mkdir()
    groups={'01-ELT-Core':['ELT/app','ELT/config','ELT/terminology','ELT/runtime','ELT/native'],
            '02-ASR-Model':['ELT/models'],'03-GPU-Runtime':['ELT/tools/gpu-runtime']}
    if (distribution/'tools/vlc-3.0.24').is_dir():groups['04-VLC']=['ELT/tools/vlc-3.0.24']
    groups['01-ELT-Core']+=['ELT/'+p.name for p in distribution.iterdir() if p.is_file()]
    groups['01-ELT-Core']+=['ELT/tools/'+p.name for p in (distribution/'tools').iterdir()
                              if p.name not in ('gpu-runtime','vlc-3.0.24')]
    if (distribution/'docs').is_dir():groups['01-ELT-Core']+=['ELT/docs']
    logs=output/'build-logs';logs.mkdir()
    for name,paths in groups.items():
        print(json.dumps({'event':'compress_started','group':name}),flush=True)
        command=[str(sevenzip),'a','-t7z','-mx=3','-mmt=4','-md=32m','-ms=64m',f'-v{VOLUME_BYTES}b','-bsp0','-xr!__pycache__',str(packages/(name+'.7z')),*paths]
        with (logs/(name+'.txt')).open('wb') as log:
            subprocess.run(command,cwd=distribution.parent,stdout=log,stderr=subprocess.STDOUT,check=True)
        print(json.dumps({'event':'compress_finished','group':name}),flush=True)
    return packages,list(groups)


def finish(output:Path,packages:Path,groups,sevenzip:Path):
    shutil.copy2(sevenzip,packages/'7za.exe')
    license_file=sevenzip.parent/'License.txt'
    if not license_file.exists():license_file=sevenzip.parent.parent/'License.txt'
    if not license_file.exists():raise FileNotFoundError('7-Zip license missing')
    shutil.copy2(license_file,packages/'7-Zip-LICENSE.txt')
    shutil.copy2(ROOT/'tools/package_licenses/Whisper-LICENSE.txt',packages/'Whisper-LICENSE.txt')
    sums=[]
    for path in sorted(packages.glob('*.7z.*')):
        if not 0<path.stat().st_size<=400_000_000:raise ValueError('volume exceeds 400 MB')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        sums.append({'file':path.name,'bytes':path.stat().st_size,'sha256':digest})
    (packages/'packages.json').write_text(json.dumps({'max_file_bytes':400_000_000,'volume_bytes':VOLUME_BYTES,'files':sums},indent=2),encoding='utf-8')
    commands=''.join(f'"%~dp07za.exe" t "%~dp0{name}.7z.001" -bsp0\nif errorlevel 1 goto failed\n' for name in groups)
    commands+=''.join(f'"%~dp07za.exe" x "%~dp0{name}.7z.001" -o"%~dp0" -aos -bsp0\nif errorlevel 1 goto failed\n' for name in groups)
    write_cmd(packages/'一键解压.cmd','@echo off\nsetlocal\ncd /d "%~dp0"\nif exist "%~dp0ELT\\" goto exists\n'+commands+
        'echo Finished. Open ELT and double-click its launcher.\nexplorer.exe "%~dp0ELT"\npause\nexit /b 0\n'+
        ':exists\necho ELT already exists. Rename that folder before extracting again. No files were overwritten.\npause\nexit /b 1\n'+
        ':failed\necho Extraction failed. Keep all volumes together and check the error above.\npause\nexit /b 1\n')
    (packages/'先读我-解压与启动.txt').write_text(
        'ELT 空白便携版 — 四组分卷包\n\n'
        '请把本目录所有文件放在同一个文件夹，不要改名，不要单独解压后面的 .002/.003 卷。\n'
        '双击“一键解压.cmd”，会先检查四组压缩数据，再解压到旁边的 ELT 文件夹。\n'
        '进入 ELT，双击“启动ELT.cmd”。首次自行配置 API Key；原来电脑的密钥、字幕、日志、设置未打包。\n'
        '如果 ELT 文件夹已经存在，解压脚本会停止，避免覆盖；请先自行改名后重试。\n'
        '也可用已安装的 7-Zip，依次解压四组的 .7z.001 到同一位置，合并 ELT 文件夹。\n'
        '每卷最多 390,000,000 字节，低于 400 MB。packages.json 和 SHA256SUMS.txt 列出大小与摘要。\n'
        '01=程序和 Python 依赖；02=识别模型；03=GPU 库；04=VLC。使用浏览器也仍需 01/02/03。\n'
        '建议解压到较短的本地路径，并至少保留 10 GB 空间。Windows 11 x64；GPU 识别需兼容 NVIDIA 驱动。\n'
        '此包不包含未启用的 Qwen 模型、Build Tools、安装缓存或测试素材。\n',encoding='utf-8')
    all_checksums=[]
    for path in sorted(packages.iterdir()):
        if path.name=='SHA256SUMS.txt':continue
        if not path.is_file() or path.stat().st_size>400_000_000:raise ValueError('oversized delivery file')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        all_checksums.append(f'{digest}  {path.name}\n')
    (packages/'SHA256SUMS.txt').write_text(''.join(all_checksums),encoding='utf-8')
    print(json.dumps({'event':'packaged','volumes':len(sums),'compressed_bytes':sum(x['bytes'] for x in sums),'max_volume':max(x['bytes'] for x in sums)}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--python-base',type=Path,default=Path(sys.base_prefix));parser.add_argument('--sevenzip',type=Path,required=True)
    args=parser.parse_args();output=args.output.resolve();sevenzip=args.sevenzip.resolve()
    if not output.is_relative_to(ROOT/'dist') or output==ROOT/'dist':parser.error('output must be a fresh child of project dist/')
    if output.exists():parser.error('output already exists; choose a new directory')
    if not sevenzip.is_file():parser.error('7-Zip executable missing')
    output.mkdir(parents=True)
    distribution,info=stage(output,args.python_base.resolve())
    print(json.dumps({'event':'staged','profile':info['profile']}),flush=True)
    files=inventory(distribution,progress=True)
    (distribution/'files.manifest.json').write_text(json.dumps({'format':1,'files':files},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'event':'audited','files':len(files),'bytes':sum(f['bytes'] for f in files)}),flush=True)
    packages,groups=compress(output,distribution,sevenzip)
    finish(output,packages,groups,sevenzip)


if __name__=='__main__':main()
