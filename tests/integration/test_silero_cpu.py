"""Real bundled ONNX inference on CPU, independent of GPU or downloaded audio."""
import numpy as np
import pytest


def test_real_vad_chunk_boundaries_preserve_recurrent_state():
    pytest.importorskip('onnxruntime')
    pytest.importorskip('faster_whisper')
    from app.asr.vad import SileroStream
    from app.asr.config import ASRConfig
    rng=np.random.default_rng(3)
    noise=(rng.standard_normal(16000)*.005).astype(np.float32)
    whole=SileroStream(ASRConfig());events1=whole.feed(noise)
    stream=SileroStream(ASRConfig());events2=[]
    for i in range(0,len(noise),320):events2.extend(stream.feed(noise[i:i+320]))
    assert events1==events2
    assert whole.position==stream.position==15872
    assert len(stream.pending)==128
    np.testing.assert_allclose(whole.h,stream.h,atol=1e-6)
    np.testing.assert_allclose(whole.c,stream.c,atol=1e-6)
