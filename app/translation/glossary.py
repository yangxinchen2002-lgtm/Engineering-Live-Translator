from __future__ import annotations
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import unicodedata
from app.languages import SOURCE_LANGUAGES


@dataclass(frozen=True)
class Term:
    source_term: str
    target_translation: str
    domain: str
    context_note: str
    source_language: str = 'any'


class Glossary:
    def __init__(self, entries: list[Term]):
        self.entries = tuple(entries)

    @classmethod
    def load(cls,path:Path) -> Glossary:
        with path.open('rb') as source:
            raw = source.read(131073)
        if len(raw)>131072: raise ValueError('glossary exceeds 128 KiB')
        data = json.loads(raw.decode('utf-8-sig'))
        if not isinstance(data,dict) or set(data)!={'version','entries'} or type(data['version']) is not int or data['version']!=1:
            raise ValueError('invalid glossary schema/version')
        if not isinstance(data['entries'],list) or len(data['entries'])>512:
            raise ValueError('glossary exceeds 512 entries')
        entries,seen = [],set()
        for item in data['entries']:
            required = {'source_term','target_translation','domain','context_note'}
            if not isinstance(item,dict) or not required<=item.keys() or item.keys()-required-{'source_language'}:
                raise ValueError('invalid glossary entry fields')
            for key,limit in [('source_term',80),('target_translation',80),('domain',40),('context_note',320)]:
                value = item[key]
                if (not isinstance(value,str) or (not value.strip() and key!='context_note') or len(value)>limit
                        or any(unicodedata.category(c).startswith('C') for c in value)):
                    raise ValueError(f'invalid glossary {key}')
            term = Term(**item)
            if term.source_language not in ('any',*SOURCE_LANGUAGES): raise ValueError('invalid glossary language')
            key = (term.source_language,term.domain,term.source_term.casefold())
            if key in seen: raise ValueError('duplicate glossary entry in the same domain/language')
            seen.add(key);entries.append(term)
        return cls(entries)

    def relevant(self,text:str,language:str,domain:str,count:int,char_limit:int,*,target_language='zh') -> list[dict]:
        if target_language not in ('zh','en'):raise ValueError('invalid glossary target')
        english={(t.domain,t.target_translation):t.source_term for t in self.entries if t.source_language=='en'}
        text = unicodedata.normalize('NFKC',text).casefold()
        selected,size = [],0
        # Domain preference never rewrites text; ambiguous entries keep their notes.
        entries = sorted(self.entries,key=lambda t:(bool(domain) and t.domain!=domain,-len(t.source_term)))
        for term in entries:
            if term.source_language not in ('any',language): continue
            needle = unicodedata.normalize('NFKC',term.source_term).casefold()
            # Japanese terms occur next to particles without word separators.
            # Keep Latin-word boundaries even inside Japanese source material.
            cjk = any('\u3040'<=c<='\u30ff' or '\u3400'<=c<='\u9fff' or '\uff66'<=c<='\uff9f'
                      or '\uac00'<=c<='\ud7af' for c in needle)
            matched = needle in text if language in ('ja','zh','ko') and cjk else re.search(r'(?<!\w)'+re.escape(needle)+r'(?!\w)',text)
            if not matched: continue
            item = asdict(term)
            if target_language=='en':
                equivalent=term.source_term if term.source_language=='en' else english.get((term.domain,term.target_translation))
                if not equivalent:continue
                item['target_translation']=equivalent
            length = len(json.dumps(item,ensure_ascii=False))
            if len(selected)>=count: break
            if size+length>char_limit: continue
            selected.append(item);size+=length
        return selected
