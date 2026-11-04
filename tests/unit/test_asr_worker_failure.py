from types import SimpleNamespace
import sys
import pytest
from app.asr.config import ASRConfig
from app.asr import worker


def test_gpu_missing_does_not_silently_fallback(monkeypatch):
    calls=[];messages=[]
    monkeypatch.setattr(worker,'configure_gpu_runtime',lambda:[])
    monkeypatch.setitem(sys.modules,'ctranslate2',SimpleNamespace(get_cuda_device_count=lambda:0))
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=lambda *a,**k:calls.append(k)))
    output=SimpleNamespace(put=lambda item,timeout:messages.append(item))
    with pytest.raises(SystemExit) as error:worker.worker_main(ASRConfig(),None,output)
    assert error.value.code==1 and calls==[]
    assert 'no CPU fallback' in messages[0]['error']


def test_invalid_profile_fails_before_cuda_initialization(monkeypatch,tmp_path):
    def unexpected():raise AssertionError('CUDA must not initialize for a missing vocabulary')
    monkeypatch.setattr(worker,'configure_gpu_runtime',unexpected)
    messages=[]
    output=SimpleNamespace(put=lambda item,timeout:messages.append(item))
    with pytest.raises(SystemExit):
        worker.worker_main(ASRConfig(course_terms=str(tmp_path/'missing.toml')),None,output)
    assert messages[0]['type']=='error' and 'missing.toml' in messages[0]['error']


def test_worker_applies_profile_only_after_matching_language_lock(monkeypatch,tmp_path):
    import numpy as np
    from app.asr.types import ASRJob,RATE
    p=tmp_path/'course.toml'
    p.write_text('version=1\nname="Firmware"\nlanguage="de"\nterms=["Kernel"]',encoding='utf-8')
    calls=[];messages=[]
    class Model:
        max_length=448
        hf_tokenizer=SimpleNamespace(encode=lambda *a,**k:SimpleNamespace(ids=[1,2]))
        model=SimpleNamespace(device='cuda',compute_type='float16')
        def transcribe(self,audio,**options):
            calls.append(options)
            segment=SimpleNamespace(text=' Kernel',words=[SimpleNamespace(word=' Kernel',start=0,end=.2)])
            return iter([segment]),SimpleNamespace(language='de',language_probability=.99)
    monkeypatch.setattr(worker,'configure_gpu_runtime',lambda:[])
    monkeypatch.setitem(sys.modules,'ctranslate2',SimpleNamespace(get_cuda_device_count=lambda:1,__version__='test'))
    monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=lambda *a,**k:Model()))
    jobs=iter([ASRJob(i,1,0,RATE,np.zeros(RATE,np.float32),False,False,0,0,language=lang)
               for i,lang in enumerate([None,'en','de'])]+[None])
    worker.worker_main(ASRConfig(language='auto',course_terms=str(p)),SimpleNamespace(get=lambda:next(jobs)),
                       SimpleNamespace(put=lambda item,timeout:messages.append(item)))
    assert [c.get('hotwords') for c in calls]==[None,None,None,'Kernel']
    results=[m['result'] for m in messages if m['type']=='result']
    assert [r.course_terms_applied for r in results]==[False,False,True]
    assert messages[0]['course_terms']['hint_tokens']==2
