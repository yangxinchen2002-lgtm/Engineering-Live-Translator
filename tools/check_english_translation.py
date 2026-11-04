"""Two fixed text-only requests using the saved key; no capture or course data."""
import argparse
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    from app.translation.config import TranslationConfig
    from app.translation.credentials import read_credential
    from app.translation.client import DeepSeekClient
    from app.translation.runtime import run_text
    credential=read_credential()
    if credential is None:raise RuntimeError('No saved DeepSeek key; live test not executed')
    async def run():
        rows=[]
        for mode in ('sentence','preview'):
            config=replace(TranslationConfig(),target_language='en',mode=mode,max_retries=0).validate()
            events=[]
            summary=await run_text('Die Matrix ist nicht invertierbar.','de',config,
                lambda event,**data:events.append((event,data)),client=DeepSeekClient(config,credential))
            records=[data for event,data in events if event=='subtitle' and data.get('state')=='final']
            if not records:
                # Event schema is stable and tested separately; do not mark an
                # empty or unavailable translation as a successful live check.
                raise RuntimeError('No final English subtitle; live test failed')
            text=records[-1]['translated_text']
            assert text and not re.search('[\u3400-\u9fff]',text)
            rows.append(dict(mode=mode,target_language='en',source_language='de',translation=text,
                final_subtitles=summary['final_subtitles'],reported_usage=summary.get('token_usage',{})))
        return rows
    rows=asyncio.run(run());args.output.parent.mkdir(parents=True,exist_ok=True)
    report=dict(cases=rows,source='fixed engineering test sentence',course_audio_uploaded=False,key_logged=False)
    args.output.write_text(json.dumps(report,indent=2)+'\n','utf-8');print(json.dumps(report));return 0


if __name__=='__main__':raise SystemExit(main())
