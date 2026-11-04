"""User-facing native desktop entry point; no capture starts at launch."""
from app.i18n import tr as _tr
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont,QIcon
from .window import MainWindow,STYLE
from .preferences import PreferencesStore,default_path


def main():
    app=QApplication(sys.argv)
    app.setApplicationName('Engineering Live Translator');app.setOrganizationName('ELT')
    app.setWindowIcon(QIcon(str(Path(__file__).with_name('assets')/'elt.ico')))
    app.setStyle('Fusion');app.setFont(QFont('Microsoft YaHei UI',10));app.setStyleSheet(STYLE)
    warning=''
    try:preferences=PreferencesStore(default_path())
    except OSError:preferences=None;warning=_tr('外观设置位置不可用，本次不保存设置；仍可正常使用字幕。')
    window=MainWindow(preferences=preferences,enable_global_shortcuts=True);window.show()
    if '--web-follow' in sys.argv:window.capture_mode.setCurrentIndex(window.capture_mode.findData('web'))
    if warning:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0,lambda:window.show_problem(warning))
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
