"""Render the actual idle widgets offscreen; this is not desktop/hardware acceptance."""
import argparse
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--web-follow',action='store_true')
    parser.add_argument('--ui-language',choices=('zh','en'),default='zh')
    parser.add_argument('--target-language',choices=('zh','en'),default='zh')
    parser.add_argument('--speech-engine',choices=('qwen','system'))
    from app.translation.providers import PROVIDERS
    parser.add_argument('--provider',choices=tuple(PROVIDERS),default='deepseek')
    from app.languages import ASR_LANGUAGES
    parser.add_argument('--language',choices=ASR_LANGUAGES)
    parser.add_argument('--show-transcripts',action='store_true',help='show the opt-in transcript settings section')
    parser.add_argument('--tab',choices=('course','translation','speech','transcripts'),default='course')
    parser.add_argument('--show-ai-notes',action='store_true')
    parser.add_argument('--show-catch-up',action='store_true')
    parser.add_argument('--size',type=int,nargs=2,metavar=('WIDTH','HEIGHT'))
    parser.add_argument('--dialog',choices=('appearance','performance','key'))
    args=parser.parse_args()
    if args.output.exists():parser.error('choose a new output file')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont,QFontDatabase
    from PySide6.QtTest import QTest
    from PySide6.QtCore import QEventLoop,QTimer
    from app.ui.window import MainWindow,STYLE
    app=QApplication([])
    # Offscreen/isolated Windows sessions may not enumerate installed fonts.
    # Read the user's installed font; never copy or redistribute the font file.
    if 'Microsoft YaHei UI' not in QFontDatabase.families():
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/msyh.ttc'
        if font.is_file():QFontDatabase.addApplicationFont(str(font))
    app.setStyle('Fusion');app.setFont(QFont('Microsoft YaHei UI',10));app.setStyleSheet(STYLE)
    from app.ui.preferences import PreferencesStore,UISettings
    args.output.parent.mkdir(parents=True,exist_ok=True)
    store=PreferencesStore(args.output.with_suffix('.settings.json'))
    store.save(UISettings(ui_language=args.ui_language,target_language=args.target_language))
    window=MainWindow(preferences=store)
    window.translation_provider.setCurrentIndex(window.translation_provider.findData(args.provider))
    if args.language:window.language.setCurrentIndex(window.language.findData(args.language))
    if args.web_follow:window.capture_mode.setCurrentIndex(window.capture_mode.findData('web'))
    if args.size:window.resize(*args.size)
    window.show();app.processEvents();QTest.qWait(500)
    if args.speech_engine=='system':
        window.speech_model.setCurrentIndex(window.speech_model.findData('system'))
        wait=QEventLoop();poll=QTimer();poll.setInterval(50)
        poll.timeout.connect(lambda:wait.quit() if window.web_voice.currentData() is not None or '未找到' in window.web_voice.currentText() else None)
        poll.start();QTimer.singleShot(6000,wait.quit);wait.exec();poll.stop()
    window.settings_tabs.setCurrentWidget({'course':window.course_scroll,'translation':window.translation_scroll,
                                          'speech':window.speech_scroll,'transcripts':window.settings_scroll}[args.tab])
    if args.show_transcripts:window.show_transcript_settings()
    if args.show_ai_notes:
        window.settings_tabs.setCurrentWidget(window.settings_scroll)
        window.settings_scroll.ensureWidgetVisible(window.summary_button)
    if args.show_catch_up:
        window.settings_tabs.setCurrentWidget(window.speech_scroll)
        window.speech_scroll.ensureWidgetVisible(window.speech_catch_grace)
    app.processEvents();target=window
    if args.dialog:
        from app.ui.appearance import AppearanceDialog,PerformanceDialog
        from app.ui.window import KeyDialog
        if args.dialog=='appearance':target=AppearanceDialog(window.settings_snapshot(),window)
        elif args.dialog=='performance':target=PerformanceDialog(window.controller,window)
        else:target=KeyDialog(window.controller,{'available':False},window)
        target.show();app.processEvents();QTest.qWait(100)
    try:
        if not target.grab().save(str(args.output)):raise OSError('could not save widget preview')
    finally:
        if target is not window:target.close();app.processEvents()
        window.close();app.processEvents()
    return 0


if __name__=='__main__':raise SystemExit(main())
