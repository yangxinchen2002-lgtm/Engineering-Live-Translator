"""Length-bounded chronological suffix of confirmed source/translation pairs."""
from __future__ import annotations
import json


def json_text(value) -> str:
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def context_chars(items:list[dict]) -> int:
    """Serialized Unicode characters, including separators; empty history is 0."""
    return len(json_text(items)) if items else 0


def bounded_context(items:list[dict],count:int,char_limit:int) -> list[dict]:
    """Evict oldest whole pairs; never skip a newer pair to revive older ones."""
    if not count or not char_limit:return []
    retained=[{key:item[key] for key in ('source_text','translated_text')} for item in items[-count:]]
    while retained and context_chars(retained)>char_limit:retained.pop(0)
    return retained
