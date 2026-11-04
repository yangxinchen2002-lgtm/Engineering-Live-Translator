"""Prepare 100-case manual review, or explicitly --run real DeepSeek calls. No mock outputs."""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.translation.client import DeepSeekClient,ProviderError
from app.translation.config import TranslationConfig
from app.translation.credentials import read_credential
from app.translation.evaluation import load_cases,review_row,screen
from app.translation.glossary import Glossary
from app.translation.prompt import messages


async def evaluate(dataset,config,client,output,run):
    rows=[review_row(case) for case in dataset['cases']]
    summary={'case_count':len(rows),'real_api_requested':run,'real_api_executed':False,
             'reference_status':dataset['reference_status'],'human_quality_status':'not_reviewed',
             'automatic_checks_are_semantic_accuracy':False,'completed':0,'failed':0,
             'not_run':0,
             'token_usage':{},'attempts_without_usage':0,'cost_usd':None}
    if not run or client is None:
        summary['not_run']=len(rows)
        summary['status']='review_prepared' if not run else 'not_executed_missing_credentials'
    else:
        summary['real_api_executed']=True
        summary['status']='running'
        glossary=Glossary.load(Path(config.glossary));semaphore=asyncio.Semaphore(config.concurrency)
        fatal_error=[None]
        async def one(row):
            async with semaphore:
                if fatal_error[0]:
                    row.update(api_status='not_run_fatal_provider_error',error_code=fatal_error[0])
                    summary['not_run']+=1;return
                for attempt in range(config.max_retries+1):
                    current=replace(config,domain=row['domain'])
                    prompt=messages(row['source'],row['language'],[],glossary,current)
                    text='';usage=None;first=None;done=False;started=time.perf_counter_ns()
                    async def consume():
                        nonlocal text,usage,first,done
                        async for event in client.stream(prompt):
                            if event.kind=='delta':
                                text+=event.text
                                if first is None and text.strip():first=time.perf_counter_ns()
                            elif event.kind=='usage':usage=event.usage
                            elif event.kind=='done':done=True
                    error=None
                    try:
                        await asyncio.wait_for(consume(),config.request_timeout_seconds)
                        if not done:raise ProviderError('incomplete_translation_stream')
                    except TimeoutError:error=ProviderError('request_deadline',retryable=True)
                    except ProviderError as exc:
                        error=exc
                        if usage is None:usage=exc.usage
                    finally:
                        if usage is None:summary['attempts_without_usage']+=1
                        else:
                            for key,value in usage.items():summary['token_usage'][key]=summary['token_usage'].get(key,0)+value
                    if error is None:
                        row.update(translated_text=text,api_status='completed',attempts=attempt+1,
                                   first_output_seconds=(first-started)/1e9 if first else None,
                                   request_seconds=(time.perf_counter_ns()-started)/1e9,
                                   automatic_flags=screen(row['source'],text))
                        summary['completed']+=1;return
                    if not error.retryable or attempt==config.max_retries:
                        if error.fatal:fatal_error[0]=error.code
                        row.update(api_status='failed',error_code=error.code,attempts=attempt+1)
                        summary['failed']+=1;return
                    await asyncio.sleep(min(2.,max(error.retry_after,config.retry_delay_seconds*2**attempt)))
        try:await asyncio.gather(*(one(row) for row in rows))
        except BaseException:
            summary['status']='interrupted'
            summary['not_run']=sum(row['api_status'].startswith('not_run') for row in rows)
            raise
        finally:
            (output/'review.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        summary['status']='api_complete_review_pending' if not summary['failed'] else 'api_partial_review_pending'
    (output/'review.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,default=ROOT/'tests/fixtures/m2_engineering_sentences.json')
    p.add_argument('--config',type=Path,default=ROOT/'config/translation.toml')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--run',action='store_true',help='explicitly send the 100 source sentences to DeepSeek')
    a=p.parse_args();a.output=a.output.resolve();a.output.mkdir(parents=True,exist_ok=False)
    dataset=load_cases(a.dataset);config=TranslationConfig.load(a.config)
    (a.output/'dataset-sha256.txt').write_text(hashlib.sha256(a.dataset.read_bytes()).hexdigest(),encoding='utf-8')
    async def run():
        credential=read_credential() if a.run else None
        client=DeepSeekClient(config,credential) if credential else None
        try:return await evaluate(dataset,config,client,a.output,a.run)
        finally:
            if client:await client.close()
    summary=asyncio.run(run());print(json.dumps(summary,ensure_ascii=False))
    return 0 if not a.run or summary['completed']==100 else 3


if __name__=='__main__':raise SystemExit(main())
