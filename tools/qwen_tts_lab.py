"""Isolated offline Chinese TTS audition and real Whisper/TTS concurrency measurements.

Run the orchestrator with ELT's original Python; the TTS subprocess uses .venv-tts.
No audio capture, cloud translation, credentials, or changes to the production app.
"""
import argparse
from dataclasses import asdict
import html
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MODEL = ROOT / 'models/Qwen3-TTS-12Hz-0.6B-CustomVoice'
PREFIX = '@ELT_TTS_TEST '
CASES = [
    {'id': 'lecture', 'text': '请注意，这里的矩阵必须是方阵。可惜，这个方法只适用于线性系统。现在先把条件说明清楚，再按顺序介绍计算步骤。', 'speaker': 'lecture_male'},
    {'id': 'ordinary', 'text': '今天我们学习线性代数。请先理解矩阵的含义，再看后面的计算过程。', 'speaker': 'serena'},
    {'id': 'technical', 'text': '如果雅可比矩阵是奇异矩阵，它的逆矩阵就不存在。请注意，这个结论有一个前提：矩阵必须是方阵。', 'speaker': 'serena'},
    {'id': 'polyphones', 'text': '银行行长正在检查这一行数据。请重新测量这块金属的重量，并记录温度变化。这个方案还需要调整，调整完成以后，再把仪器还给实验室。', 'speaker': 'serena'},
    {'id': 'long_chinese', 'text': '这一节我们先讨论系统为什么会产生振荡。你可能会问：只要把增益调小，系统就一定稳定吗？答案是，不一定。判断稳定性时，既要考虑反馈的方向，也要考虑系统本身的动态特性。如果忽略了时间延迟，即使计算过程没有错误，最后得到的结论也可能不适用于真实设备。因此，我们先建立模型，再检查假设，最后用实验验证结果。', 'speaker': 'serena'},
    {'id': 'numbers', 'text': '采样频率为48000赫兹，电压为3.3伏，误差不超过0.5%。请把2026年11月1日的结果记录下来。', 'speaker': 'serena'},
    {'id': 'mixed', 'text': '我们使用 Transformer 模型处理输入，再通过 CPU 和 GPU 分担计算任务。这里的 PID 控制器包含比例、积分和微分三个部分。', 'speaker': 'serena'},
    {'id': 'symbols', 'text': '设矩阵 A 的特征值 λ 小于零。当 s 趋于零时，传递函数 G(s) 的极限为一。请注意，x² 表示 x 的平方。', 'speaker': 'serena'},
    {'id': 'vivian', 'text': '今天我们学习线性代数。请先理解矩阵的含义，再看后面的计算过程。', 'speaker': 'vivian'},
    {'id': 'uncle_fu', 'text': '今天我们学习线性代数。请先理解矩阵的含义，再看后面的计算过程。', 'speaker': 'uncle_fu'},
]


def emit(value):
    print(PREFIX + json.dumps(value, ensure_ascii=False), flush=True)


def tts_worker(engine, device='cuda',model_size='0.6B'):
    # Offline throughout inference, even if a third-party library tries to fetch metadata.
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', HF_HOME=str(ROOT / '.tmp/hf-tts'),
                      TORCH_HOME=str(ROOT / '.tmp/torch-tts'))
    import numpy as np
    import soundfile as sf
    import torch
    started = time.perf_counter_ns()
    from app.speech.runtime import SpeechEngine
    runtime=SpeechEngine(device,model_size=model_size,official_gpu=engine=='official')
    model=runtime.model;underlying=model.model.model if runtime.fast else model.model
    if device=='cuda':torch.cuda.synchronize()
    devices = sorted({str(p.device) for p in underlying.parameters()})
    codec_devices = sorted({str(p.device) for p in underlying.speech_tokenizer.model.parameters()})
    if any(not d.startswith(device) for d in devices):
        raise RuntimeError(f'not all model parameters are on GPU: {devices}')
    if any(not d.startswith(device) for d in codec_devices):
        raise RuntimeError(f'not all speech codec parameters are on GPU: {codec_devices}')
    emit({'type': 'ready', 'engine': engine, 'load_s': (time.perf_counter_ns()-started)/1e9,
          'torch': torch.__version__, 'gpu': torch.cuda.get_device_name() if device=='cuda' else 'CPU', 'devices': devices,
          'dtype': str(next(underlying.parameters()).dtype), 'model': runtime.info['model'], 'model_size':model_size,'codec_devices': codec_devices,
          'parameter_count': sum(p.numel() for p in underlying.parameters()),
          'allocated_bytes': torch.cuda.memory_allocated() if device=='cuda' else 0,
          'reserved_bytes': torch.cuda.memory_reserved() if device=='cuda' else 0})
    for line in sys.stdin:
        request = json.loads(line)
        if request.get('type') == 'stop':
            return
        try:
            text = request['text'].strip()
            if not text or len(text) > 400:
                raise ValueError('text must contain 1 to 400 characters')
            output = Path(request['output']).resolve()
            if not output.is_relative_to(ROOT) or output.exists():
                raise ValueError('output must be a new file inside the workspace')
            output.parent.mkdir(parents=True, exist_ok=True)
            torch.manual_seed(request.get('seed', 20261101))
            if device=='cuda':torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
            start = time.perf_counter_ns()
            chunks, chunk_times = [], []
            for wave,rate in runtime.generate(text,request.get('speaker','serena')):
                if device=='cuda':torch.cuda.synchronize()
                chunks.append(wave);chunk_times.append({'ready_ns':time.perf_counter_ns(),'samples':len(wave)})
            if device=='cuda':torch.cuda.synchronize()
            finish = time.perf_counter_ns()
            if not chunks:
                raise RuntimeError('no audio produced')
            wave = np.concatenate(chunks)
            if not np.isfinite(wave).all() or np.sqrt(np.mean(wave.astype('float64')**2)) < 1e-5:
                raise RuntimeError('invalid or silent audio')
            duration = len(wave)/rate
            sf.write(str(output), wave, rate, subtype='PCM_16')
            # Minimal prebuffer needed for gapless delivery, computed from chunk arrival times.
            delivered = 0.0
            prebuffer = 0.0
            for row in chunk_times:
                prebuffer = max(prebuffer, (row['ready_ns']-start)/1e9-delivered)
                delivered += row['samples']/rate
            emit({'type': 'result', 'id': request['id'], 'engine': engine, 'text': text,
                  'speaker': request.get('speaker','serena'), 'output': str(output), 'start_ns': start,
                  'finish_ns': finish, 'generation_s': (finish-start)/1e9,
                  'first_audio_s': (chunk_times[0]['ready_ns']-start)/1e9,
                  'duration_s': duration, 'sample_rate': rate, 'chunks': chunk_times,
                  'wave_peak': float(np.max(np.abs(wave))), 'samples_outside_pcm_range': int(np.sum(np.abs(wave)>1)),
                  'generation_per_audio_s': (finish-start)/1e9/duration,
                  'minimum_gapless_prebuffer_s': prebuffer,
                  'possibly_token_limited': duration >= 1024*.08*.97,
                  'peak_allocated_bytes': torch.cuda.max_memory_allocated() if device=='cuda' else 0,
                  'peak_reserved_bytes': torch.cuda.max_memory_reserved() if device=='cuda' else 0})
        except Exception as error:
            emit({'type': 'error', 'id': request.get('id'), 'message': str(error),
                  'traceback': traceback.format_exc()})


class TTSSession:
    def __init__(self, engine, directory, device='cuda',*,model_size='0.6B'):
        self.queue = queue.Queue()
        self.log = (directory/'tts-process.log').open('w', encoding='utf-8')
        environment = dict(os.environ)
        environment.pop('DEEPSEEK_API_KEY', None)
        environment.update(PYTHONUTF8='1', HF_HOME=str(ROOT/'.tmp/hf-tts'),
                           TORCH_HOME=str(ROOT/'.tmp/torch-tts'))
        self.process = subprocess.Popen([str(ROOT/'.venv-tts/Scripts/python.exe'), '-u', __file__,
                            'worker', '--engine', engine, '--device', device,'--model-size',model_size], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                            bufsize=1, env=environment, cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
        import win32api
        import win32job
        self.owner_job = win32job.CreateJobObject(None, '')
        info = win32job.QueryInformationJobObject(self.owner_job, win32job.JobObjectExtendedLimitInformation)
        info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(self.owner_job, win32job.JobObjectExtendedLimitInformation, info)
        handle = win32api.OpenProcess(0x0100 | 0x0001, False, self.process.pid)
        try:
            win32job.AssignProcessToJobObject(self.owner_job, handle)
        finally:
            handle.Close()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()
        try:
            self.ready = self.receive(180)
            if self.ready.get('type') != 'ready':
                raise RuntimeError(str(self.ready))
        except BaseException:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            self.log.write(line)
            self.log.flush()
            if line.startswith(PREFIX):
                self.queue.put(json.loads(line[len(PREFIX):]))
        self.queue.put({'type': 'error', 'message': f'TTS process exited {self.process.poll()}'})

    def receive(self, timeout=240):
        value = self.queue.get(timeout=timeout)
        if value.get('type') == 'error':
            raise RuntimeError(value.get('message', str(value)))
        return value

    def request(self, case, output):
        self.process.stdin.write(json.dumps({**case, 'output': str(output)}, ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        return self.receive()

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.stdin.write('{"type":"stop"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
                self.process.wait(timeout=5)
        self.thread.join(timeout=3)
        self.log.close()
        self.owner_job.Close()


def load_asr():
    from app.asr.config import ASRConfig
    from app.asr.worker import ASRWorker
    worker = ASRWorker(ASRConfig())
    deadline = time.perf_counter()+180
    try:
        while not worker.ready:
            if time.perf_counter() > deadline:
                raise TimeoutError('ASR startup timeout')
            value = worker.poll()
            if value and value['type'] == 'ready':
                return worker, value
            time.sleep(.005)
    except BaseException:
        worker.close()
        raise


def audio(path, seconds=48):
    from tools.measure_local_translation import audio_excerpt
    return audio_excerpt(path, seconds)


def jobs():
    sources = [('en', ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4'),
               ('de', ROOT/'tests/fixtures/public-m1/de-neural-networks.mp3')]
    values = {lang: audio(path) for lang, path in sources}
    return [(index, lang, values[lang][(20+index//2)*16000:(28+index//2)*16000])
            for index in range(24) for lang in [('en' if index % 2 == 0 else 'de')]]


def asr_jobs(worker, inputs, interval=1.0,until=None):
    from app.asr.types import ASRJob
    rows = []
    origin = time.perf_counter_ns()
    index=0
    while index<len(inputs) or (until is not None and not until.is_set()):
        if index>=240:raise TimeoutError('concurrent measurement exceeds four minutes')
        case,language,samples=inputs[index%len(inputs)]
        due = origin + round(index*interval*1e9)
        while time.perf_counter_ns() < due:
            time.sleep(.002)
        submitted = time.perf_counter_ns()
        worker.submit(ASRJob(index, 1, 0, len(samples), samples, True, True,
                            submitted, submitted, language=language))
        deadline = time.perf_counter()+45
        while True:
            if time.perf_counter() > deadline:
                raise TimeoutError('ASR inference timeout')
            message = worker.poll()
            if message and message['type'] == 'result':
                result = message['result']
                worker.busy = None
                received = time.perf_counter_ns()
                rows.append({**asdict(result), 'fixture_language': language, 'fixture_case': case, 'scheduled_ns': due,
                             'submitted_ns': submitted, 'received_ns': received,
                             'inference_s': (result.finished_ns-result.started_ns)/1e9,
                             'response_s': (received-submitted)/1e9,
                             'schedule_lag_s': (submitted-due)/1e9})
                print(json.dumps({'asr_job': index, 'language': language,
                                  'inference_s': rows[-1]['inference_s']}, ensure_ascii=False), flush=True)
                break
            time.sleep(.002)
        index+=1
    return rows


def benchmark(args):
    from tools.tts_sampling import Sampler
    directory = args.output.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    from app.speech.config import MODEL_PATHS
    results = {'engine': args.engine, 'device':args.device, 'smoke': args.smoke, 'model': str(MODEL_PATHS[args.model_size]),'model_size':args.model_size,
               'tts_alone': [], 'tts_concurrent': [], 'asr_alone': [], 'asr_concurrent': [],
               'measurement': 'QPC wall time; NVML whole-device VRAM sampled every 20ms; no audio playback/capture'}
    sampler = Sampler()
    tts = worker = None
    thread = None
    try:
        time.sleep(.5)
        selected_cases=CASES if not args.quick else [
            {'id':'ordinary','text':'你好，这是中文朗读测试。','speaker':'serena'},
            {'id':'technical','text':'这个矩阵的逆不存在。','speaker':'serena'}]
        if args.speaker:selected_cases=[{**case,'speaker':args.speaker} for case in selected_cases]
        inputs = [] if args.smoke else jobs()
        if not args.smoke:
            print('ASR-only reference measurements', flush=True)
            sampler.stage = 'asr_load'
            worker, results['asr_ready_alone'] = load_asr()
            sampler.stage = 'asr_alone'
            results['asr_alone'] = asr_jobs(worker, inputs)
            worker.close()
            worker = None
        print('Loading TTS checkpoint', flush=True)
        sampler.stage = 'tts_load'
        tts = TTSSession(args.engine, directory,args.device,model_size=args.model_size)
        results['tts_ready'] = tts.ready
        sampler.stage = 'tts_cold'
        results['tts_cold'] = tts.request(selected_cases[0], directory/'cold-serena.wav')
        sampler.stage = 'tts_alone'
        for case in (selected_cases[:1] if args.smoke else selected_cases):
            value = tts.request(case, directory/f"alone-{case['id']}.wav")
            results['tts_alone'].append(value)
            print(json.dumps({k: value[k] for k in ('id','generation_s','first_audio_s','duration_s')}, ensure_ascii=False), flush=True)
        if not args.smoke:
            print('Loading ASR alongside TTS', flush=True)
            sampler.stage = 'both_load'
            worker, results['asr_ready_concurrent'] = load_asr()
            sampler.stage = 'both_resident'
            time.sleep(.5)
            # No inference call from either library runs in the UI thread.
            # TTS is intentionally continuous, a stronger load than playback-paced generation.
            errors = []
            tts_finished=threading.Event()
            def continuous_tts():
                try:
                    started = time.perf_counter()
                    selected = [r for r in selected_cases if r['id'] in ('lecture','ordinary','technical','polyphones','long_chinese','mixed')]
                    for index in range(12):
                        case = selected[index % len(selected)]
                        value = tts.request({**case, 'id': f'concurrent-{index}-{case["id"]}'},
                                            directory/f'concurrent-{index:02d}.wav')
                        results['tts_concurrent'].append(value)
                        print(json.dumps({k: value[k] for k in ('id','generation_s','first_audio_s','duration_s')}, ensure_ascii=False), flush=True)
                        if index >= 3 and time.perf_counter()-started >= 30:
                            break
                except BaseException as error:
                    errors.append(str(error))
                finally:tts_finished.set()
            sampler.stage = 'concurrent_inference'
            thread = threading.Thread(target=continuous_tts)
            thread.start()
            results['asr_concurrent'] = asr_jobs(worker, inputs,until=tts_finished)
            thread.join(timeout=300)
            if thread.is_alive():
                raise TimeoutError('concurrent TTS thread timeout')
            if errors:
                raise RuntimeError(errors[0])
            # Readback is an automatic content check, not a human naturalness rating.
            sampler.stage = 'chinese_readback'
            from app.asr.types import ASRJob
            results['chinese_readback'] = []
            for index, row in enumerate(results['tts_alone']):
                samples = audio(Path(row['output']), seconds=90)
                now = time.perf_counter_ns()
                worker.submit(ASRJob(1000+index, 1, 0, len(samples), samples, True, True, now, now, language='zh'))
                deadline = time.perf_counter()+45
                while True:
                    if time.perf_counter() > deadline:
                        raise TimeoutError('Chinese readback timeout')
                    value = worker.poll()
                    if value and value['type'] == 'result':
                        worker.busy = None
                        results['chinese_readback'].append({'id': row['id'], 'reference': row['text'],
                                                           'recognized': value['result'].text})
                        break
                    time.sleep(.005)
    except BaseException as error:
        results['error'] = {'type': type(error).__name__, 'message': str(error), 'traceback': traceback.format_exc()}
        print(results['error']['traceback'], flush=True)
    finally:
        if thread and thread.is_alive():
            if tts:
                tts.close()
                tts = None
            thread.join(timeout=10)
        if worker:
            worker.close()
        if tts:
            tts.close()
        sampler.stage = 'cleanup'
        time.sleep(.5)
        sampler.close()
        results['sampling_error'] = sampler.error
        (directory/'memory-samples.json').write_text(json.dumps(sampler.rows, indent=2), encoding='utf-8')
        stages = sorted({x['stage'] for x in sampler.rows})
        results['vram'] = {stage: {'peak_bytes': max(x['used_bytes'] for x in sampler.rows if x['stage']==stage),
                                  'sample_count': sum(x['stage']==stage for x in sampler.rows)} for stage in stages}
        overlap = [r for r in results['asr_concurrent'] if any(
            r['started_ns'] < t['finish_ns'] and t['start_ns'] < r['finished_ns'] for t in results['tts_concurrent'])]
        results['overlapped_asr_count'] = len(overlap)
        def summarize(rows, keys):
            import numpy as np
            return {key: {'n': len(rows), 'p50': float(np.percentile([r[key] for r in rows], 50)),
                          'p95': float(np.percentile([r[key] for r in rows], 95)), 'max': max(r[key] for r in rows)}
                    for key in keys} if rows else {}
        results['summary'] = {
            'asr_alone': summarize(results['asr_alone'], ['inference_s','response_s','schedule_lag_s']),
            'asr_overlapping': summarize(overlap, ['inference_s','response_s','schedule_lag_s']),
            'tts_alone': summarize(results['tts_alone'], ['first_audio_s','generation_s','generation_per_audio_s','minimum_gapless_prebuffer_s']),
            'tts_concurrent': summarize(results['tts_concurrent'], ['first_audio_s','generation_s','generation_per_audio_s','minimum_gapless_prebuffer_s'])}
        if results['asr_alone'] and results['asr_concurrent']:
            expected={row['fixture_case']:row['text'] for row in results['asr_alone']}
            results['asr_identical_transcripts'] = sum(expected[b['fixture_case']]==b['text'] for b in results['asr_concurrent'])
        results['passed'] = bool(not results.get('error') and not sampler.error and results['tts_alone'] and
                                 not any(r['possibly_token_limited'] for r in results['tts_alone']+results['tts_concurrent']) and
                                 (args.smoke or len(overlap) >= 8))
        (directory/'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'passed': results['passed'], 'vram': results['vram'], 'summary': results['summary'],
                          'overlapped_asr_count': len(overlap)}, ensure_ascii=False), flush=True)
    return 0 if results['passed'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    worker = sub.add_parser('worker')
    worker.add_argument('--engine', choices=['official','fast'], required=True)
    worker.add_argument('--device',choices=['cuda','cpu'],default='cuda')
    bench = sub.add_parser('benchmark')
    bench.add_argument('--engine', choices=['official','fast'], required=True)
    bench.add_argument('--output', type=Path, required=True)
    bench.add_argument('--smoke', action='store_true')
    bench.add_argument('--device',choices=['cuda','cpu'],default='cuda')
    bench.add_argument('--quick',action='store_true')
    bench.add_argument('--speaker')
    speak = sub.add_parser('speak')
    speak.add_argument('--engine', choices=['official','fast'], default='fast')
    speak.add_argument('--device',choices=['cuda','cpu'],default='cuda')
    speak.add_argument('--text')
    speak.add_argument('--text-file', type=Path)
    speak.add_argument('--speaker', default='serena')
    speak.add_argument('--output', type=Path, required=True)
    for command in (worker,bench,speak):command.add_argument('--model-size',choices=['0.6B','1.7B'],default='0.6B')
    args = parser.parse_args()
    if args.command == 'worker':
        tts_worker(args.engine,args.device,args.model_size)
        return 0
    if args.command == 'speak':
        text = args.text_file.read_text(encoding='utf-8-sig') if args.text_file else args.text
        if not text:
            parser.error('speak requires --text or --text-file')
        output = args.output.resolve()
        if not output.is_relative_to(ROOT) or output.exists():
            parser.error('output must be a new file inside this project')
        output.parent.mkdir(parents=True, exist_ok=True)
        session = TTSSession(args.engine, output.parent,args.device,model_size=args.model_size)
        try:
            print(json.dumps(session.request({'id': 'manual', 'text': text, 'speaker': args.speaker}, output),
                             ensure_ascii=False, indent=2))
        finally:
            session.close()
        return 0
    return benchmark(args)


if __name__ == '__main__':
    raise SystemExit(main())
