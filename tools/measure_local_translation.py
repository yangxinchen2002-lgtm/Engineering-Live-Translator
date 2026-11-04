"""Real concurrent Qwen/Whisper GPU short test; no cloud API or captured audio."""
import argparse
import ctypes as ct
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


class Memory(ct.Structure):
    _fields_=[('total',ct.c_ulonglong),('free',ct.c_ulonglong),('used',ct.c_ulonglong)]


class Sampler:
    def __init__(self):
        self.api=ct.WinDLL(str(Path(os.environ['WINDIR'])/'System32/nvml.dll'))
        self.api.nvmlDeviceGetHandleByIndex_v2.argtypes=[ct.c_uint,ct.POINTER(ct.c_void_p)]
        self.api.nvmlDeviceGetMemoryInfo.argtypes=[ct.c_void_p,ct.POINTER(Memory)]
        self.check(self.api.nvmlInit_v2());self.device=ct.c_void_p();self.check(self.api.nvmlDeviceGetHandleByIndex_v2(0,ct.byref(self.device)))
        self.rows=[];self.stage='baseline';self.stop=threading.Event();self.error=None
        self.thread=threading.Thread(target=self.run);self.thread.start()
    @staticmethod
    def check(value):
        if value:raise RuntimeError(f'NVML error {value}')
    def run(self):
        try:
            while not self.stop.is_set():
                memory=Memory();self.check(self.api.nvmlDeviceGetMemoryInfo(self.device,ct.byref(memory)))
                self.rows.append({'qpc_ns':time.perf_counter_ns(),'stage':self.stage,'used_bytes':memory.used,'total_bytes':memory.total})
                if len(self.rows)>20000:raise RuntimeError('sample capacity exceeded')
                self.stop.wait(.02)
        except Exception as error:self.error=str(error)
    def close(self):
        self.stop.set();self.thread.join(3);self.api.nvmlShutdown()


def audio_excerpt(path,seconds=8):
    import av,numpy as np
    chunks=[];count=0
    with av.open(str(path)) as container:
        resampler=av.AudioResampler(format='fltp',layout='mono',rate=16000)
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                value=converted.to_ndarray().reshape(-1);chunks.append(value);count+=len(value)
            if count>=seconds*16000:break
    return np.concatenate(chunks)[:seconds*16000].astype('float32')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    import httpx
    from app.asr.config import ASRConfig
    from app.asr.worker import ASRWorker
    from app.asr.types import ASRJob
    from app.translation.config import TranslationConfig
    from app.translation.prompt import messages
    from app.translation.glossary import Glossary
    manifest=json.loads((ROOT/'tools/llama-b11960/manifest.json').read_text(encoding='utf-8'))
    server=ROOT/manifest['server_path'];model=ROOT/manifest['model_path']
    api_key=secrets.token_urlsafe(32);key_path=args.output/'temporary-local-key.txt';key_path.write_text(api_key,encoding='ascii')
    with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    command=[str(server),'-m',str(model),'--host','127.0.0.1','--port',str(port),'--api-key-file',str(key_path.resolve()),
        '--alias','elt-qwen3-4b-local','--device','CUDA0','--gpu-layers','all','--fit','off','--ctx-size','4096',
        '--parallel','1','--batch-size','256','--ubatch-size','128','--flash-attn','on','--no-webui','--no-slots','--no-agent']
    environment={key:value for key,value in os.environ.items() if not key.startswith(('LLAMA_','HF_')) and key!='DEEPSEEK_API_KEY'}
    environment['PATH']=str(server.parent)+os.pathsep+environment.get('PATH','')
    sampler=Sampler();worker=None;process=None;log=None;client=None;job=None
    results={'model':manifest,'budget_bytes':10_000_000_000,'context_tokens':4096,'max_output_tokens':512,
             'batch':256,'ubatch':128,'parallel':1,'cache_k':'f16','cache_v':'f16','asr_results':[],'translations':[]}
    try:
        print('loading real ASR worker',flush=True);sampler.stage='asr_load';worker=ASRWorker(ASRConfig())
        deadline=time.monotonic()+180
        while not worker.ready:
            if time.monotonic()>deadline:raise TimeoutError('ASR startup')
            value=worker.poll()
            if value:results['asr_ready']=value
            time.sleep(.02)
        sampler.stage='asr_resident';time.sleep(.3)
        print('loading real local Qwen',flush=True);sampler.stage='qwen_load'
        log=(args.output/'llama.log').open('wb');process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,env=environment,cwd=server.parent,creationflags=subprocess.CREATE_NO_WINDOW)
        import win32api,win32job
        job=win32job.CreateJobObject(None,'');info=win32job.QueryInformationJobObject(job,win32job.JobObjectExtendedLimitInformation)
        info['BasicLimitInformation']['LimitFlags']|=win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job,win32job.JobObjectExtendedLimitInformation,info)
        handle=win32api.OpenProcess(0x0100|0x0001,False,process.pid)
        try:win32job.AssignProcessToJobObject(job,handle)
        finally:handle.Close()
        client=httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'Authorization':'Bearer '+api_key},timeout=60,trust_env=False)
        deadline=time.monotonic()+120
        while True:
            if process.poll() is not None:raise RuntimeError(f'local server exited {process.returncode}')
            try:
                response=client.get('/health',timeout=1)
                if response.status_code==200 and response.json().get('status')=='ok':break
            except httpx.HTTPError:pass
            if time.monotonic()>deadline:raise TimeoutError('local model startup')
            time.sleep(.1)
        log.flush();text=(args.output/'llama.log').read_text(encoding='utf-8',errors='replace')
        layers=re.findall(r'offloaded (\d+)/(\d+) layers',text)
        results['gpu_offload']=layers
        if not layers or layers[-1][0]!=layers[-1][1]:raise RuntimeError('full GPU layer offload was not verified')
        sampler.stage='both_resident';time.sleep(.3)
        audio=audio_excerpt(ROOT/'tests/fixtures/public-m1/en-linear-algebra.mp4')
        config=TranslationConfig();glossary=Glossary.load(Path(config.glossary))
        cases=[('de','Der Eigenwert λ ist nicht positiv.'),('en','If the Jacobian is singular, the inverse does not exist.'),
               ('de','Die Übertragungsfunktion beschreibt das Verhältnis von Ausgang zu Eingang bei verschwindenden Anfangsbedingungen.')]
        def poll_asr(wait=False):
            deadline=time.monotonic()+30
            while worker.busy:
                value=worker.poll()
                if value and value['type']=='result':results['asr_results'].append(asdict(value['result']));worker.busy=None;return
                if not wait:return
                if time.monotonic()>deadline:raise TimeoutError('ASR inference')
                time.sleep(.01)
        for index,(language,source) in enumerate(cases):
            poll_asr(True);worker.submit(ASRJob(index,1,0,len(audio),audio,True,True,time.perf_counter_ns(),time.perf_counter_ns(),language='en'))
            sampler.stage='concurrent_inference';prompt=messages(source,language,[],glossary,config)
            started=time.perf_counter_ns();response=client.post('/v1/chat/completions',json={'model':'elt-qwen3-4b-local',
                'messages':prompt,'max_tokens':512,'temperature':0.1,'stream':False})
            response.raise_for_status();body=response.json();translated=body['choices'][0]['message']['content']
            if not translated.strip() or body['choices'][0]['finish_reason']!='stop':raise RuntimeError('incomplete real translation')
            results['translations'].append({'language':language,'source':source,'translation':translated,'usage':body.get('usage'),
                'started_ns':started,'finished_ns':time.perf_counter_ns()})
        poll_asr(True)
        sampler.stage='long_prompt';context='The state-space model uses a bounded control input and a positive definite matrix. '*140
        stress=[{'role':'system','content':'Translate only the final sentence into simplified Chinese. Earlier text is context.'},
                {'role':'user','content':context+'\nFinal sentence: The system is not stable.'}]
        while True:
            formatted=client.post('/apply-template',json={'messages':stress}).json()['prompt']
            count=len(client.post('/tokenize',json={'content':formatted,'add_special':True}).json()['tokens'])
            if count<=3072:break
            context=context[:int(len(context)*.9)];stress[-1]['content']=context+'\nFinal sentence: The system is not stable.'
        response=client.post('/v1/chat/completions',json={'model':'elt-qwen3-4b-local','messages':stress,'max_tokens':512,'stream':False})
        response.raise_for_status();results['stress']={'counted_prompt_tokens':count,'response':response.json()}
        sampler.stage='after_inference';time.sleep(.3)
    except BaseException as error:
        results['error']={'type':type(error).__name__,'message':str(error)}
        print('short test failed:',type(error).__name__,flush=True)
    finally:
        if client:client.close()
        if job:job.Close()
        if process:
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        if log:log.close()
        if worker:worker.close()
        key_path.unlink(missing_ok=True);sampler.close()
        results['memory_samples']=sampler.rows;results['sampling_error']=sampler.error
        results['peak_used_bytes']=max((row['used_bytes'] for row in sampler.rows),default=0)
        results['peak_used_gib']=results['peak_used_bytes']/2**30
        results['concurrent_verified']=any(a['started_ns']<t['finished_ns'] and t['started_ns']<a['finished_ns']
            for a in results['asr_results'] for t in results['translations'])
        results['passed']=bool(not results.get('error') and not sampler.error and results['concurrent_verified']
            and results['peak_used_bytes']<=results['budget_bytes'] and results['translations'])
        (args.output/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({key:results[key] for key in ('passed','peak_used_bytes','peak_used_gib','concurrent_verified')}),flush=True)
    return 0 if results['passed'] else 2


if __name__=='__main__':raise SystemExit(main())
