"""Render the shared vector icon and build the Windows GUI-subsystem launcher."""
import argparse
import os
from pathlib import Path
import struct
import subprocess
import shutil

ROOT=Path(__file__).resolve().parents[1]
ICON_SIZES=(16,20,24,32,40,48,64,96,128,256)


def render_icon(renderer,size):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage,QPainter
    image=QImage(size,size,QImage.Format_ARGB32);image.fill(Qt.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter);painter.end()
    return image


def encode_ico(renderer):
    from PySide6.QtCore import QBuffer,QIODevice
    frames=[]
    for size in ICON_SIZES:
        data=QBuffer();data.open(QIODevice.WriteOnly)
        if not render_icon(renderer,size).save(data,'PNG'):raise OSError('Icon PNG encoding failed')
        frames.append((size,bytes(data.data())))
    offset=6+16*len(frames);entries=[]
    for size,png in frames:
        dimension=0 if size==256 else size
        entries.append(struct.pack('<BBBBHHII',dimension,dimension,0,0,1,32,len(png),offset))
        offset+=len(png)
    return struct.pack('<HHH',0,1,len(frames))+b''.join(entries)+b''.join(png for _,png in frames)


def write_icons(preview=None):
    from PySide6.QtSvg import QSvgRenderer
    renderer=QSvgRenderer(str(ROOT/'app/ui/assets/elt.svg'))
    if not renderer.isValid():raise ValueError('ELT vector icon is invalid')
    icon=encode_ico(renderer)
    (ROOT/'native/launcher/elt.ico').write_bytes(icon)
    (ROOT/'app/ui/assets/elt.ico').write_bytes(icon)
    if preview is not None:
        preview.parent.mkdir(parents=True,exist_ok=True)
        if not render_icon(renderer,256).save(str(preview)):raise OSError('Could not save icon preview')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--icons-only',action='store_true')
    parser.add_argument('--preview',type=Path)
    args=parser.parse_args()
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    app=QApplication.instance() or QApplication([])
    write_icons(args.preview)
    if args.icons_only:return 0
    tools=ROOT/'tools/buildtools';cmake=tools/'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'
    subprocess.run([str(cmake),'-S',str(ROOT/'native/launcher'),'-B',str(ROOT/'native/launcher-build'),
                    '-G','Visual Studio 17 2022','-A','x64','-DCMAKE_GENERATOR_INSTANCE='+str(tools)],check=True)
    subprocess.run([str(cmake),'--build',str(ROOT/'native/launcher-build'),'--config','Release'],check=True)
    launcher=ROOT/'native/launcher-build/Release/ELT.exe'
    shutil.copy2(launcher,ROOT/'ELT.exe');shutil.copy2(launcher,ROOT/'创建桌面快捷方式.exe')


if __name__=='__main__':main()
