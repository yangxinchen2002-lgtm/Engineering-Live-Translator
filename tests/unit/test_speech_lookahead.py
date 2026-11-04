"""Keep synthesis busy through short/long sentence transitions, without merging."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from app.speech.config import SpeechConfig
from app.ui.speech import SpeechController
from tests.unit.test_speech_pipeline import Process
from tests.unit.test_speech_and_course_notes import record


def test_ready_short_next_sentence_does_not_idle_the_worker_while_a_long_sentence_plays():
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True)
    speech.active=True;speech.ready=True;speech.process=Process()
    texts=['首先完整说明这个结论的适用条件，以及每一步计算应当注意的问题。','请注意，',
           '接下来核对矩阵的维数和边界条件，确保每个计算步骤都符合定义。','然后继续。','最后验证结果。']
    for index,text in enumerate(texts):speech.offer(record(index,translated=text))
    speech.current['playing']=True
    speech._event({'event':'speech_done','id':'1'})
    assert [row['text'] for row in speech.process.commands]==texts[:2]
    speech._event({'event':'speech_done','id':'2'})
    # Keep decoding the third sentence during the long first sentence, rather
    # than wait for it to finish and discover the second is too short to cover it.
    assert [row['text'] for row in speech.process.commands]==texts[:3]
    speech._event({'event':'speech_done','id':'3'})
    assert [row['text'] for row in speech.process.commands]==texts[:4]
    speech._event({'event':'speech_done','id':'4'})
    assert len(speech.process.commands)==4  # Three following utterances is the bound.
    assert speech.generating_id is None and len(speech.queue)==1
    speech.current=None;speech._next()
    assert speech.current['text']==texts[1]
    assert [row['text'] for row in speech.process.commands]==texts
    speech.stop();assert not speech.prefetched and not speech.queue and speech.generating_id is None
    speech.close();app.processEvents()


def test_pcm_limit_includes_every_prepared_utterance():
    import base64
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True)
    speech.active=True;speech.ready=True;speech.process=Process();problems=[]
    speech.problem.connect(problems.append)
    for index in range(4):speech.offer(record(index,translated=f'第{index}句。'))
    for identity in ('1','2','3'):speech._event({'event':'speech_done','id':identity})
    for utterance in (speech.current,*speech.prefetched):utterance['raw_bytes']=8*1024*1024
    speech._event({'event':'speech_audio','id':'4','rate':24000,'pcm':base64.b64encode(b'\x01\x00').decode()})
    assert problems and speech.paused and speech.current is None and not speech.prefetched
    speech.close();app.processEvents()


def test_tiny_sentence_prefill_does_not_make_later_long_sentences_look_slow():
    app=QApplication.instance() or QApplication([])
    speech=SpeechController();speech.timer.stop();speech.config=SpeechConfig(True)
    speech.active=True;speech.ready=True;speech.process=Process()
    for index,text in enumerate(['这是一段完整的课堂说明。','可惜，','接下来继续说明条件。']):
        speech.offer(record(index,translated=text))
    speech._event({'event':'speech_done','id':'1','audio_seconds':4.,'generation_seconds':3.,'first_audio_seconds':.4})
    speech.prefetched[0]['largest_chunk_gap']=.9
    speech._event({'event':'speech_done','id':'2','audio_seconds':1.28,'generation_seconds':1.9,'first_audio_seconds':1.})
    assert max(rate for rate,_ in speech.generation_history)==.75
    assert max(gap for _,gap in speech.generation_history)==.9
    speech.close();app.processEvents()
