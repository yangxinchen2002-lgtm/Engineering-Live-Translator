"""Real formal-GUI/backend/GPU/file/transcript lifecycle, no cloud or browser control."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));os.environ.setdefault('QT_QPA_PLATFORM','offscreen')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    os.environ['ELT_PROFILE_ID']='portable-'+uuid.uuid4().hex
    os.environ['ELT_WEB_RUNTIME_DIR']=str((args.output.parent/'runtime').resolve())
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QDesktopServices
    from app.ui.window import MainWindow,STYLE
    from app.ui.preferences import PreferencesStore
    import httpx,psutil
    app=QApplication([]);app.setStyleSheet(STYLE)
    window=MainWindow(preferences=PreferencesStore(args.output.parent/'test-settings.json'))
    window.web_player_choice.setCurrentIndex(window.web_player_choice.findData('edge'))
    window.show();QTest.qWait(200)
    result={'cloud_calls':0,'test_clock':'Explicit local-file test clock, not a live webpage measurement'}
    client=None;worker_pid=None;backend_pid=None
    def wait(check,seconds=120):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            app.processEvents()
            if check():return
            QTest.qWait(30)
        raise TimeoutError('formal web-follow check timed out')
    try:
        directory=args.output.parent/'transcripts';directory.mkdir(exist_ok=True)
        window.transcript_directory=directory.resolve();window.save_transcripts_check.setChecked(True)
        window.capture_mode.setCurrentIndex(window.capture_mode.findData('web'))
        window.language.setCurrentIndex(window.language.findData('en'))
        window.translate_check.setChecked(False);window.speech_check.setChecked(False)
        with patch.object(QDesktopServices,'openUrl',return_value=True):
            started=time.monotonic();window.start_capture();wait(lambda:bool(window.web_connect_url),15)
        assert window.controller.running and window.controller.web_mode
        backend_pid=window.controller.backend_pid
        u=urlsplit(window.web_connect_url);origin=f'{u.scheme}://{u.netloc}'
        client=httpx.Client(base_url=origin,headers={'X-ELT-Lab-Token':u.fragment},trust_env=False,timeout=10)
        config=dict(source=str(ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4'),position=20,language='en',
                    provider='deepseek',model='deepseek-flash',translate=False,narrate=False,voice=0,lookahead=15)
        response=client.post('/api/start',json=config);response.raise_for_status()
        worker_pid=response.json()['worker_pid']
        snapshot={}
        def prepared():
            nonlocal snapshot
            snapshot=client.get('/api/state').json()
            if snapshot['status']=='error':raise RuntimeError(snapshot['error'])
            return snapshot['prepared_until']>=35 and snapshot['status']=='ready'
        wait(prepared)
        result['first_prepare_wall_seconds']=round(time.monotonic()-started,3)
        for position in (20.5,21):
            response=client.post('/api/clock',json=dict(position=position,paused=False,rate=1,seek=False))
            response.raise_for_status();QTest.qWait(300)
        wait(lambda:window.controller.course.available,5)
        record=window.controller.model.current
        assert record and record['source_text'].strip() and not record['translated_text']
        assert record['start_sample']<=21*16000<record['end_sample']
        assert not window.speech.active and window.speech.process is None
        assert window.pause_button.isEnabled() is False
        result['formal_caption_real']=True;result['current_source_chars']=len(record['source_text'])
        result['future_sentences_not_shown']=all(row['start_sample']<=21*16000 for row in window.controller.model.records.values())
        assert result['future_sentences_not_shown']
        result['native_qwen_not_started']=True
        window.controller.stop();wait(lambda:not window.controller.running,15)
        assert not window.controller.forced
        result['worker_reaped']=not psutil.pid_exists(worker_pid)
        result['service_reaped']=not psutil.pid_exists(backend_pid)
        assert result['worker_reaped'] and result['service_reaped']
        assert window.last_transcript_path and window.last_transcript_path.is_file()
        transcript=window.last_transcript_path.read_text(encoding='utf-8')
        assert record['source_text'] in transcript and '英语' in window.last_transcript_path.name
        result['transcript_saved']=True;result['transcript_filename']=window.last_transcript_path.name
        result['temp_sessions_left']=len(list(Path(os.environ['ELT_WEB_RUNTIME_DIR']).glob('session-*')))
        assert result['temp_sessions_left']==0
        # Also load the original ASR worker after web shutdown to verify lease
        # release and the native path's real model startup. No captured audio.
        from app.asr.config import ASRConfig
        from app.asr.worker import ASRWorker
        native=ASRWorker(ASRConfig.load(ROOT/'config/asr.toml',language='en',course_terms=''))
        native_pid=native.process.pid
        try:
            ready=None;deadline=time.monotonic()+100
            while time.monotonic()<deadline:
                value=native.poll()
                if value and value['type']=='ready':ready=value;break
                QTest.qWait(50)
            assert ready and ready['device']=='cuda'
            result['original_asr_gpu_startup']=True
        finally:native.close()
        assert not psutil.pid_exists(native_pid);result['original_asr_worker_reaped']=True
        print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:
        if client:client.close()
        if window.controller.running:
            window.controller.stop()
            try:wait(lambda:not window.controller.running,15)
            except TimeoutError:window.controller.force_stop();QTest.qWait(500)
        window.close();QTest.qWait(300)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
