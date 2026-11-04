from types import SimpleNamespace
import numpy as np
import pytest
from app.asr.decoding import pathological,decode,segment_words


def test_normal_repeated_engineering_words_are_not_rejected():
    assert not pathological('very very small matrix a matrix b',3)
    assert pathological('the color of '*80,.6)


def test_repetition_uses_real_second_decode_not_text_replacement():
    class Model:
        def __init__(self):self.calls=[]
        def transcribe(self,audio,**options):
            self.calls.append(options)
            return iter([SimpleNamespace(text='the color of '*80 if len(self.calls)==1 else 'the column')]),None
    model=Model();segments,info,retried,count=decode(model,np.zeros(16000,np.float32),'en')
    assert retried and count==240 and segments[0].text=='the column'
    assert model.calls[0]['beam_size']==1 and model.calls[0]['vad_filter'] is False
    assert model.calls[1]['no_repeat_ngram_size']==4


def test_persistent_pathology_fails_explicitly():
    class Model:
        def transcribe(self,*args,**kwargs):return iter([SimpleNamespace(text='the color of '*80)]),None
    with pytest.raises(RuntimeError):decode(Model(),np.zeros(16000,np.float32),'en')


def test_hotwords_survive_retry_and_off_mode_is_unchanged():
    class Model:
        def __init__(self):self.calls=[]
        def transcribe(self,audio,**options):
            self.calls.append(options)
            return iter([SimpleNamespace(text='the color of '*80 if len(self.calls)==1 else 'Kernel')]),None
    model=Model()
    decode(model,np.zeros(16000,np.float32),'de',hotwords='Kernel, Firmware')
    assert all(c['hotwords']=='Kernel, Firmware' for c in model.calls)
    model=Model()
    decode(model,np.zeros(16000,np.float32),'de')
    assert all('hotwords' not in c and 'initial_prompt' not in c for c in model.calls)


def test_segment_word_mapping_keeps_production_clamping():
    def word(text,start,end): return SimpleNamespace(word=text,start=start,end=end)
    segments=[SimpleNamespace(words=[word(' Kernel',-.1,.3),word(' ',.3,.4),word('BIOS',.4,2)]),
              SimpleNamespace(words=None)]
    words=segment_words(segments,16000,32000)
    assert [(w.text,w.start,w.end) for w in words]==[(' Kernel',16000,20800),('BIOS',22400,32000)]
