"""Read-only runtime diagnosis; GPU enumeration is not a quality/performance benchmark."""
import ctypes
import importlib.metadata
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.asr.config import ROOT
from app.asr.worker import configure_gpu_runtime

if __name__ == '__main__':
    try:
        libraries=configure_gpu_runtime()
        loaded=[]
        for name in ['cudart64_12.dll','cublas64_12.dll','cudnn64_9.dll']:
            ctypes.WinDLL(name);loaded.append(name)
        import ctranslate2
        versions={p:importlib.metadata.version(p) for p in ['faster-whisper','ctranslate2','onnxruntime','numpy','scipy','av','setuptools']}
        result={'versions':versions,'runtime_directories':libraries,'loaded_dlls':loaded,
                'cuda_devices':ctranslate2.get_cuda_device_count(),
                'supported_compute_types':sorted(ctranslate2.get_supported_compute_types('cuda')),
                'local_model_present':(ROOT/'models/large-v3-turbo/model.bin').is_file(),
                'note':'enumeration/DLL load only; use real ASR run to validate inference'}
        print(json.dumps(result,ensure_ascii=True,indent=2))
        raise SystemExit(0 if result['cuda_devices']>0 and result['local_model_present'] else 1)
    except Exception as exc:
        print(json.dumps({'error':str(exc),'fallback_performed':False}));raise SystemExit(1)
