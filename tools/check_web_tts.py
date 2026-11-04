"""Real public-file ASR + saved cloud translation + queued Qwen TTS; no source recording."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    from app.web_follow.server import Lab
    from app.web_follow.media import Source
    import psutil
    lab=Lab();pid=None;tts_pid=None;result={'source':'existing public English linear algebra fixture',
        'cloud_translation':'Real saved DeepSeek credential; text only','test_clock':'Held at 20 seconds for preparation; no user website controlled'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    try:
        start=time.monotonic();lab.start(dict(source=str(ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4'),
            position=20,language='en',provider='deepseek',model='deepseek-flash',translate=True,narrate=True,voice=0,
            speech_engine='qwen',tts_device='cuda',tts_model='0.6B',tts_voice='serena',lookahead=15))
        pid=lab.process.pid;deadline=time.monotonic()+180;seen_source=False;seen_translation=False
        while time.monotonic()<deadline:
            lab.clock(dict(position=20,paused=True,rate=1,seek=False))
            state=lab.state()
            if state['status']=='error':raise RuntimeError(state['error'])
            if state['cues'] and not seen_source:result['first_real_source_wall_seconds']=round(time.monotonic()-start,3);seen_source=True
            if any(c['translation'] for c in state['cues']) and not seen_translation:
                result['first_real_translation_wall_seconds']=round(time.monotonic()-start,3);seen_translation=True
            tts=state['metrics'].get('tts',{});tts_pid=tts.get('pid') or tts_pid
            ready=[c for c in state['cues'] if c['speech']]
            if ready:
                import wave
                path=Path(lab.temp.name)/ready[0]['speech']
                with wave.open(str(path),'rb') as audio:
                    result['generated_audio_seconds']=audio.getnframes()/audio.getframerate();result['sample_rate']=audio.getframerate()
                    assert audio.getnframes()>0
                result['first_real_tts_wall_seconds']=round(time.monotonic()-start,3)
                result['asr_and_tts_both_cuda']=state['metrics'].get('device')=='cuda' and tts.get('device')=='cuda'
                result['translated_cues']=sum(bool(c['translation']) for c in state['cues'])
                result['usage']=state['metrics'].get('usage',{})
                result['tts_pid_reported']=bool(tts_pid);break
            time.sleep(.1)
        else:raise TimeoutError('No completed Qwen audio before deadline')
        assert result['asr_and_tts_both_cuda'] and seen_source and seen_translation
    finally:
        lab.close();result['asr_reaped']=not pid or not psutil.pid_exists(pid)
        result['tts_reaped']=not tts_pid or not psutil.pid_exists(tts_pid)
        result['temporary_wavs_removed']=lab.temp is None
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
