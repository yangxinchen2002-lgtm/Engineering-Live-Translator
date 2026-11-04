"""Real GUI -> backend startup -> authenticated HTTP -> stop; no media or cloud."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ui-language',choices=('zh','en'),default='zh')
    parser.add_argument('--target-language',choices=('zh','en'),default='zh');args=parser.parse_args()
    import httpx
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEventLoop,QTimer,QProcess
    from app.ui.window import MainWindow
    from app.ui.preferences import PreferencesStore,UISettings
    args.output.parent.mkdir(parents=True,exist_ok=True)
    store=PreferencesStore(args.output.with_suffix('.settings.json'))
    store.save(UISettings(ui_language=args.ui_language,target_language=args.target_language))
    app=QApplication([]);window=MainWindow(preferences=store);controller=window.controller
    # This startup check intentionally opens no course/player page.
    window.open_web_connect=lambda:None
    ready=[];failures=[];controller.web_ready.connect(ready.append);controller.problem.connect(failures.append)
    def wait(predicate,seconds):
        loop=QEventLoop();poll=QTimer();limit=QTimer();limit.setSingleShot(True)
        poll.timeout.connect(lambda:loop.quit() if predicate() else None);limit.timeout.connect(loop.quit)
        poll.start(50);limit.start(round(seconds*1000));loop.exec();poll.stop();limit.stop()
        if not predicate():raise TimeoutError('startup test timed out')
    report={};started=time.monotonic()
    try:
        wait(lambda:not window._loading_preferences,3)
        window.capture_mode.setCurrentIndex(window.capture_mode.findData('web'))
        window.translate_check.setChecked(False);window.speech_check.setChecked(False)
        window.web_captions.update(caption_width=65,caption_height=96,caption_font_size=14)
        window.start_capture();assert controller.running,'GUI did not start the real backend'
        wait(lambda:bool(ready) or not controller.running,15)
        assert ready and not failures,'Backend did not become ready: '+str(failures)
        address=urlsplit(ready[0]);origin=f'http://127.0.0.1:{address.port}'
        with httpx.Client(base_url=origin,headers={'X-ELT-Lab-Token':address.fragment},trust_env=False,timeout=3) as client:
            response=client.get('/api/settings');response.raise_for_status();defaults=response.json()['defaults']
            appearance={key:defaults[key] for key in window.web_captions}
            assert appearance==window.web_captions
            assert defaults['target_language']==args.target_language and defaults['ui_language']==args.ui_language
            locale=client.get('/ui-locale.js');locale.raise_for_status()
            assert 'ELTLocale' in locale.text and 'Enable translation' in locale.text
            page=client.get('/');page.raise_for_status()
            assert f'data-elt-ui-language="{args.ui_language}"' in page.text
            state=client.get('/api/state');state.raise_for_status();state=state.json()
            assert not state['has_source'] and state['worker_pid'] is None
        controller.stop();wait(lambda:not controller.running,10)
        assert not controller.forced and controller.process.state()==QProcess.NotRunning
        report=dict(gui_started=True,backend_ready=True,http_status=response.status_code,caption_settings=appearance,
            ui_language=defaults['ui_language'],target_language=defaults['target_language'],
            stopped_cleanly=True,media_started=False,gpu_model_loaded=False,cloud_requests=0,
            elapsed_seconds=round(time.monotonic()-started,3))
    finally:
        if controller.running:
            controller.force_stop();controller.process.waitForFinished(3000)
        window.close();app.processEvents()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
