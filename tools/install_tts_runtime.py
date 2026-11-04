"""Optional Qwen setup in a separate full Python 3.12 virtual environment.

The basic portable application needs no system Python. This explicit optional
setup uses full Python for Qwen's scientific stack and never reads credentials.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def python_command(executable=None):
    return [str(Path(executable).resolve())] if executable else ['py','-3.12']


def validate_python(command):
    probe="import json,struct,sys;print(json.dumps([sys.version_info.major,sys.version_info.minor,struct.calcsize('P')*8]))"
    result=subprocess.run([*command,'-I','-c',probe],check=True,capture_output=True,text=True,timeout=30)
    if json.loads(result.stdout)!=[3,12,64]:raise ValueError('Qwen requires full Windows x64 Python 3.12.')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',action='store_true')
    parser.add_argument('--python',type=Path,help='Full Python 3.12 x64 interpreter; default: py -3.12')
    args=parser.parse_args();target=ROOT/'.venv-tts'
    if not (ROOT/'distribution.json').is_file():
        parser.error('Run this tool from an extracted ELT portable package.')
    if target.exists():parser.error('.venv-tts already exists. It was not overwritten.')
    lock=ROOT/'requirements-tts-lock.txt'
    if not lock.is_file():parser.error('TTS dependency lock is missing.')
    if args.plan:
        print(json.dumps({'target':'.venv-tts','main_runtime_modified':False,'model_downloaded':False,
            'requires_full_python':'3.12 x64','torch':'2.8.0+cu128','sources':['https://pypi.org','https://download.pytorch.org/whl/cu128']}));return 0
    try:
        command=python_command(args.python);validate_python(command)
        subprocess.run([*command,'-I','-m','venv',str(target)],check=True)
        interpreter=target/'Scripts/python.exe'
        print('Downloading optional Qwen dependencies into .venv-tts. Several GB are required.',flush=True)
        subprocess.run([str(interpreter),'-m','pip','--isolated','install','--disable-pip-version-check','-r',str(lock)],check=True)
        check="import torch,qwen_tts,faster_qwen3_tts,win32job;assert torch.__version__=='2.8.0+cu128';print('Qwen runtime imports verified')"
        subprocess.run([str(interpreter),'-c',check],cwd=ROOT,check=True,timeout=300)
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        print('Qwen setup did not finish: '+str(error),file=sys.stderr)
        print('Install full Python 3.12 x64 from python.org, including its launcher. See docs/MODEL_SETUP.en.md. '
              'The main application is unchanged. If .venv-tts was created, it is incomplete; rename it before retrying.',file=sys.stderr)
        return 1
    print('Qwen runtime installed. Download a CustomVoice model, then reopen ELT. No API key was read.');return 0


if __name__=='__main__':raise SystemExit(main())
