"""Interface text only. Source transcripts and translated content stay untouched."""
from functools import lru_cache
import json
import os
from pathlib import Path

_language=os.environ.get('ELT_UI_LANGUAGE','zh')
if _language not in ('zh','en'):_language='zh'


def set_language(language):
    global _language
    if language not in ('zh','en'):raise ValueError('invalid interface language')
    _language=language;os.environ['ELT_UI_LANGUAGE']=language


def get_language():return _language


@lru_cache(maxsize=1)
def english_catalogue():
    return json.loads((Path(__file__).with_name('locales')/'en.json').read_text(encoding='utf-8'))


def tr(text):
    if not isinstance(text,str) or _language=='zh':return text
    return english_catalogue().get(text,text)
