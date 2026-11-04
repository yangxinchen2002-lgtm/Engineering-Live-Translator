"""Render all desktop settings and inspect English labels without starting a session."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtGui import QFont,QFontDatabase
    from PySide6.QtWidgets import QApplication,QWidget,QLabel,QAbstractButton,QComboBox,QTabWidget,QFontComboBox
    from PySide6.QtTest import QTest
    from app.ui.window import MainWindow,STYLE,KeyDialog
    from app.ui.preferences import PreferencesStore,UISettings
    from app.ui.appearance import AppearanceDialog,PerformanceDialog
    app=QApplication.instance() or QApplication([])
    font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc'
    if 'Microsoft YaHei UI' not in QFontDatabase.families() and font.is_file():QFontDatabase.addApplicationFont(str(font))
    app.setStyle('Fusion');app.setFont(QFont('Microsoft YaHei UI',10));app.setStyleSheet(STYLE)
    store=PreferencesStore(args.output/'preview-settings.json');store.save(UISettings(ui_language='en',target_language='en'))
    w=MainWindow(preferences=store);w.show();QTest.qWait(100)
    report={'pages':[],'untranslated':[],'clipped':[]}
    def inspect(target,name):
        app.processEvents();QTest.qWait(30)
        target.grab().save(str(args.output/(name+'.png')));report['pages'].append(name)
        for item in [target,*target.findChildren(QWidget)]:
            values=[]
            for key in ('text','windowTitle','toolTip','accessibleName','placeholderText'):
                getter=getattr(item,key,None)
                if callable(getter):
                    value=getter()
                    if isinstance(value,str):values.append(value)
            if isinstance(item,QComboBox) and not isinstance(item,QFontComboBox):values += [item.itemText(i) for i in range(item.count())]
            if isinstance(item,QTabWidget):values += [item.tabText(i) for i in range(item.count())]
            for value in values:
                if re.search('[\u3400-\u9fff]',value) and value not in ('Microsoft YaHei UI',):
                    report['untranslated'].append({'page':name,'widget':type(item).__name__,'text':value})
            # Buttons and checkboxes use a single text line; their size hint
            # includes font metrics, style padding and checkbox indicators.
            if isinstance(item,QAbstractButton) and item.isVisibleTo(target) and item.text() and item.width()+2<item.minimumSizeHint().width():
                report['clipped'].append({'page':name,'text':item.text(),'width':item.width(),'needed':item.minimumSizeHint().width()})
    try:
        for mode in ('audio','web'):
            w.capture_mode.setCurrentIndex(w.capture_mode.findData(mode))
            for index in range(w.settings_tabs.count()):
                w.settings_tabs.setCurrentIndex(index);inspect(w,f'{mode}-tab-{index}')
        w.resize(1040,620);inspect(w,'minimum-window')
        for name,dialog in [('appearance',AppearanceDialog(w.settings_snapshot(),w)),('performance',PerformanceDialog(w.controller,w)),('api-key',KeyDialog(w.controller,{'available':False},w))]:
            try:dialog.show();inspect(dialog,name)
            finally:dialog.close();app.processEvents()
        w.history_dialog.show();inspect(w.history_dialog,'subtitle-history');w.history_dialog.hide()
        w.overlay.show();inspect(w.overlay,'overlay-list')
        from dataclasses import replace
        w.overlay.apply_appearance(replace(w.settings_snapshot(),focus_mode=True));inspect(w.overlay,'overlay-focus');w.overlay.hide()
        def diagnostic():
            dialog=QApplication.activeModalWidget()
            if dialog is None:raise AssertionError('Diagnostics dialog did not open')
            inspect(dialog,'diagnostics');dialog.accept()
        QTimer.singleShot(100,diagnostic);w.show_diagnostics()
    finally:
        w.close();app.processEvents()
        # Preference writes finish through queued Qt signals. Keep this test's
        # event loop alive until its owned tasks and deferred close complete.
        for _ in range(40):
            if not w.controller.operations:break
            QTest.qWait(50)
        w.close();app.processEvents()
    (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({'pages':len(report['pages']),'untranslated':len(report['untranslated']),'clipped':report['clipped']}))
    return int(bool(report['untranslated'] or report['clipped']))


if __name__=='__main__':raise SystemExit(main())
