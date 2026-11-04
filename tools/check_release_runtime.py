"""Real relocated imports, empty UI state and optional CPU model check; no capture/cloud."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model',action='store_true');args=parser.parse_args()
    root=Path(sys.executable).resolve().parents[2]
    if sys.flags.isolated!=1:raise RuntimeError('Use the bundled isolated Python')
    from app.asr.config import ROOT
    assert ROOT==root
    from app.profile import profile_id
    info=json.loads((root/'distribution.json').read_text('utf-8'))
    assert profile_id()==info['profile']
    from app.translation.credentials import read_credential
    from app.translation.providers import PROVIDERS
    for provider in PROVIDERS:
        assert read_credential(provider) is None,'Expected an empty release credential profile'
    from app.asr.worker import configure_gpu_runtime
    configure_gpu_runtime();loaded=[]
    for name in ('cudart64_12.dll','cublas64_12.dll','cublasLt64_12.dll','cudnn64_9.dll'):
        target=next((root/'tools/gpu-runtime').rglob(name));ctypes.WinDLL(str(target));loaded.append(name)
    import ctranslate2
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEventLoop,QTimer
    from PySide6.QtGui import QFont
    from app.ui.preferences import PreferencesStore,default_path
    from app.ui.window import MainWindow,STYLE
    app=QApplication([]);app.setStyle('Fusion');app.setFont(QFont('Microsoft YaHei UI',10));app.setStyleSheet(STYLE)
    window=MainWindow(preferences=PreferencesStore(default_path()));window.show()
    def wait(predicate,seconds):
        loop=QEventLoop();poll=QTimer();limit=QTimer();limit.setSingleShot(True)
        poll.timeout.connect(lambda:loop.quit() if predicate() else None);limit.timeout.connect(loop.quit)
        poll.start(40);limit.start(int(seconds*1000));loop.exec();poll.stop();limit.stop()
        if not predicate():raise TimeoutError('release UI did not settle')
    try:
        wait(lambda:not window._loading_preferences and not window.controller.operations,8)
        assert not window.controller.running and not window.translate_check.isChecked()
        assert not window.save_transcripts_check.isChecked() and not window.credential_status.get('available')
        assert not (default_path().parent/'course-browser').exists()
        args.output.parent.mkdir(parents=True,exist_ok=True)
        assert window.grab().save(str(args.output.with_suffix('.png')))
    finally:
        window.close();app.processEvents()
        wait(lambda:not window.controller.operations,3);window.close();app.processEvents()
    report=dict(python=sys.version.split()[0],isolated=True,root=str(root),empty_api_keys=True,
        no_capture_started=True,transcript_saving_default=False,empty_browser_profile=True,
        native_gpu_libraries_loaded=loaded,cuda_devices=ctranslate2.get_cuda_device_count(),
        paid_api_requests=0,course_audio_captured=False,model_checked=False)
    if args.model:
        from faster_whisper import WhisperModel
        import numpy as np
        started=time.monotonic()
        model=WhisperModel(str(root/'models/large-v3-turbo'),device='cpu',compute_type='int8',cpu_threads=4)
        # Explicit synthetic warmup only; never publish a transcript from it.
        segments,_=model.transcribe(np.zeros(16000,np.float32),language='en',beam_size=1,vad_filter=False)
        list(segments)
        report.update(model_checked=True,model_device=model.model.device,compute_type=model.model.compute_type,
            synthetic_warmup_discarded=True,model_check_seconds=round(time.monotonic()-started,3))
        del model
    args.output.write_text(json.dumps(report,indent=2)+'\n','utf-8');print(json.dumps(report));return 0


if __name__=='__main__':raise SystemExit(main())
