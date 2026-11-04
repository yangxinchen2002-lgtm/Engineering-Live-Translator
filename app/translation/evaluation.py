"""Draft engineering evaluation corpus and screens, not a semantic quality judge."""
import json
from pathlib import Path
import re


def load_cases(path:Path) -> dict:
    with path.open('rb') as source:raw=source.read(1_000_001)
    if len(raw)>1_000_000:raise ValueError('translation dataset too large')
    data=json.loads(raw.decode('utf-8'))
    if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('cases'),list) or len(data['cases'])!=100:
        raise ValueError('expected version 1 with exactly 100 engineering cases')
    seen=set()
    for case in data['cases']:
        if not isinstance(case,dict) or set(case)!={'id','language','domain','tags','source','reference'}:raise ValueError('invalid dataset case fields')
        for name in ('id','domain','source','reference'):
            if not isinstance(case[name],str) or not case[name].strip() or len(case[name])>800:raise ValueError('invalid dataset text')
        if case['id'] in seen or case['language'] not in ('de','en'):raise ValueError('duplicate case or invalid language')
        seen.add(case['id'])
        if not isinstance(case['tags'],list) or not case['tags'] or not all(isinstance(t,str) for t in case['tags']):
            raise ValueError('invalid dataset tags')
    return data


def screen(source:str,translation:str) -> list[dict]:
    flags=[]
    def numbers(text):return set(re.findall(r'(?<!\w)[+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?',text))
    missing=numbers(source)-numbers(translation)
    if missing:flags.append({'kind':'numeric_literal_requires_review','values':sorted(missing)})
    if re.search(r'\b(not|no|nicht|kein\w*)\b',source,re.I) and not re.search(r'不|无|非|未|没',translation):
        flags.append({'kind':'possible_missing_negation_requires_review'})
    if '```' in translation or '<think>' in translation:flags.append({'kind':'unexpected_format_requires_review'})
    if not translation.strip():flags.append({'kind':'empty_translation'})
    return flags


def review_row(case:dict) -> dict:
    return {**case,'translated_text':None,'api_status':'not_run','automatic_flags':[],
            'human_review':{'status':'pending','terms_correct':None,'logic_correct':None,
                            'negation_correct':None,'numbers_formulas_correct':None,
                            'added_conclusion':None,'severity':None,'notes':''}}
