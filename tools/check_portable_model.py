"""Developer smoke check for an assembled portable runtime; synthetic warmup only."""
import ctypes
import json
import multiprocessing
from pathlib import Path
import sys
import time


def main():
    root=Path(sys.executable).resolve().parents[2]
    from app.asr.config import ROOT,ASRConfig
    from app.asr.worker import ASRWorker,configure_gpu_runtime
    assert ROOT==root,'not running from bundled application'
    paths=configure_gpu_runtime()
    loaded=[]
    for name in ('cudart64_12.dll','cublas64_12.dll','cublasLt64_12.dll','cudnn64_9.dll'):
        path=next(root.joinpath('tools/gpu-runtime').rglob(name));ctypes.WinDLL(str(path));loaded.append(name)
    import ctranslate2
    print(json.dumps({'phase':'runtime','isolated':sys.flags.isolated,'cuda_devices':ctranslate2.get_cuda_device_count(),
                      'bundled_core_dlls_loaded':loaded,'gpu_library_directories':len(paths)}),flush=True)
    # CPU prevents this distribution check loading a second model on the GPU.
    # The production worker performs its normal one-second synthetic warmup;
    # it never emits that audio as recognized course text.
    worker=ASRWorker(ASRConfig(model=str(root/'models/large-v3-turbo'),device='cpu',compute_type='int8'))
    ready=False;started=time.monotonic()
    try:
        while time.monotonic()-started<120:
            event=worker.poll()
            if event and event['type']=='ready':
                ready=True
                print(json.dumps({'phase':'model_ready','device':event['device'],'compute_type':event['compute_type'],
                    'model_load_seconds':event['model_load_seconds'],'synthetic_warmup_seconds':event['warmup_seconds'],
                    'speech_quality_test':False}),flush=True)
                break
            time.sleep(.05)
        if not ready:raise TimeoutError('bundled model smoke check timed out')
    finally:worker.close()
    print(json.dumps({'phase':'closed','worker_closed':True}),flush=True)


if __name__=='__main__':
    multiprocessing.freeze_support();main()
