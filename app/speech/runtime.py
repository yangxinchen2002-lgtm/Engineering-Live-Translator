"""Loaded only by the isolated TTS interpreter; no cloud paths or voice cloning."""
from app.i18n import tr as _tr
import os
import time
from .config import ROOT,MODEL_PATHS,LECTURE_INSTRUCTION,LECTURE_INSTRUCTION_EN,model_speaker


class SpeechEngine:
    def __init__(self,device='cuda',*,model_size='0.6B',official_gpu=False,language='zh'):
        if language not in ('zh','en'):raise ValueError('invalid speech language')
        self.language=language
        if device not in ('cuda','cpu'):raise ValueError('invalid speech device')
        if model_size not in MODEL_PATHS:raise ValueError('invalid speech model size')
        self.model_size=model_size;model_path=MODEL_PATHS[model_size]
        os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
                          HF_HOME=str(ROOT/'.tmp/hf-tts'),TORCH_HOME=str(ROOT/'.tmp/torch-tts'))
        import torch
        self.torch=torch;self.device=device;self.fast=device=='cuda' and not official_gpu
        torch.set_num_threads(2 if device=='cuda' else min(6,os.cpu_count() or 1))
        try:torch.set_num_interop_threads(1)
        except RuntimeError:pass
        if device=='cuda' and not torch.cuda.is_available():
            raise RuntimeError(_tr('GPU 不可用，请在朗读页切换为 CPU。'))
        started=time.perf_counter_ns()
        dtype=torch.bfloat16 if device=='cuda' else torch.float32
        if self.fast:
            from faster_qwen3_tts import FasterQwen3TTS
            self.model=FasterQwen3TTS.from_pretrained(str(model_path),device='cuda',dtype=dtype,attn_implementation='sdpa')
            underlying=self.model.model.model
        else:
            from qwen_tts import Qwen3TTSModel
            self.model=Qwen3TTSModel.from_pretrained(str(model_path),device_map=device,dtype=dtype,
                                                    attn_implementation='sdpa',local_files_only=True)
            underlying=self.model.model
        if device=='cuda':torch.cuda.synchronize()
        expected_size={'0.6B':'0b6','1.7B':'1b7'}[model_size]
        if underlying.tts_model_size!=expected_size or underlying.tts_model_type!='custom_voice':
            raise RuntimeError(_tr('实际载入的朗读模型与所选讲课模式不符。'))
        self.info={'device':device,'dtype':str(dtype),'load_seconds':(time.perf_counter_ns()-started)/1e9,
                   'model_size':model_size,'model':str(model_path),
                   'checkpoint_model_size':underlying.tts_model_size,
                   'torch':torch.__version__,'language':language,'engine':'faster-qwen3-tts' if self.fast else 'qwen-tts',
                   'parameter_devices':sorted({str(p.device) for p in underlying.parameters()}),
                   'codec_devices':sorted({str(p.device) for p in underlying.speech_tokenizer.model.parameters()})}
        if any(not p.startswith(device) for p in self.info['parameter_devices']+self.info['codec_devices']):
            raise RuntimeError(_tr('朗读模型的实际运行设备与选择不符。'))

    def generate(self,text,voice='serena',*,seed=None):
        import numpy as np
        speaker=model_speaker(voice)
        if not isinstance(text,str) or not 1<=len(text)<=400:
            raise ValueError('invalid voice or utterance')
        if seed is not None:self.torch.manual_seed(seed)
        options=dict(text=text,language='Chinese' if self.language=='zh' else 'English',speaker=speaker,non_streaming_mode=True,max_new_tokens=1024)
        # The 0.6B implementation discards instruct; only 1.7B is style-controllable.
        if self.model_size=='1.7B':options['instruct']=LECTURE_INSTRUCTION if self.language=='zh' else LECTURE_INSTRUCTION_EN
        if self.fast:
            for chunk,rate,timing in self.model.generate_custom_voice_streaming(**options,chunk_size=8):
                chunk=np.asarray(chunk,dtype=np.float32).reshape(-1)
                if chunk.size:yield chunk,int(rate)
        else:
            waves,rate=self.model.generate_custom_voice(**options)
            wave=np.asarray(waves[0],dtype=np.float32).reshape(-1)
            for start in range(0,len(wave),15360):yield wave[start:start+15360],int(rate)
