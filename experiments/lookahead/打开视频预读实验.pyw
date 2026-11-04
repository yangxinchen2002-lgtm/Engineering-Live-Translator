"""Double-click entry: an independent hidden server, no change to ELT.exe."""
from pathlib import Path
import subprocess
import ctypes
import sys
import runpy

def main():
    root = Path(__file__).resolve().parents[2]
    python = root / '.venv/Scripts/pythonw.exe'
    try:
        if not python.is_file():
            raise FileNotFoundError('没有找到 ELT 的 Python 环境，请保留实验文件在原项目内。')
        if Path(sys.executable).resolve() != python.resolve():
            subprocess.Popen([str(python), '-B', str(Path(__file__).resolve())], cwd=root,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return
        sys.path.insert(0, str(root))
        sys.argv = ['elt-gui', '--web-follow']
        runpy.run_module('app.ui.main', run_name='__main__')
    except Exception as error:
        ctypes.windll.user32.MessageBoxW(None, '实验启动失败：' + str(error), 'ELT 视频预读实验', 0x10)


if __name__ == '__main__':
    main()
