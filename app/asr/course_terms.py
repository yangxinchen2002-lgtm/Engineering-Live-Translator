"""Small local course vocabularies used only as ASR hotwords, never replacements."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from pathlib import Path
import tomllib
import unicodedata
from app.languages import ASR_LANGUAGES, SOURCE_LANGUAGES

MAX_FILE_BYTES = 16_384
MAX_TERMS = 48
MAX_HINT_TOKENS = 128


@dataclass(frozen=True)
class CourseTerms:
    name: str
    language: str
    terms: tuple[str, ...]
    sources: tuple[str, ...]
    path: str
    sha256: str

    @classmethod
    def load(cls, path: Path, language: str = 'auto') -> CourseTerms:
        with path.open('rb') as source:
            raw = source.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError('course vocabulary exceeds 16 KiB')
        data = tomllib.loads(raw.decode('utf-8-sig'))
        allowed = {'version', 'name', 'language', 'terms', 'sources'}
        if data.keys() - allowed:
            raise ValueError(f'unknown course vocabulary fields: {sorted(data.keys()-allowed)}')
        if type(data.get('version')) is not int or data['version'] != 1:
            raise ValueError('course vocabulary version must be 1')
        name = data.get('name')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValueError('course vocabulary name must contain 1..100 characters')
        profile_language = data.get('language')
        if profile_language not in SOURCE_LANGUAGES:
            raise ValueError(f"course vocabulary language must be one of {', '.join(SOURCE_LANGUAGES)}")
        if language not in ASR_LANGUAGES or language not in ('auto', profile_language):
            raise ValueError('course vocabulary does not match the selected ASR language')
        terms = data.get('terms')
        if not isinstance(terms, list) or not 1 <= len(terms) <= MAX_TERMS:
            raise ValueError(f'course vocabulary must contain 1..{MAX_TERMS} terms')
        cleaned, keys = [], set()
        for term in terms:
            if (not isinstance(term, str) or not 1 <= len(term.strip()) <= 80
                    or any(unicodedata.category(c).startswith('C') for c in term)):
                raise ValueError('each course term must contain 1..80 printable characters')
            term = ' '.join(term.split())
            key = unicodedata.normalize('NFKC', term).casefold()
            if key in keys:
                raise ValueError(f'duplicate course term: {term}')
            keys.add(key)
            cleaned.append(term)
        sources = data.get('sources', [])
        if (not isinstance(sources, list) or len(sources) > 8
                or any(not isinstance(s, str) or not 1 <= len(s) <= 1024 for s in sources)):
            raise ValueError('invalid course vocabulary sources')
        return cls(name.strip(), profile_language, tuple(cleaned), tuple(sources),
                   str(path.resolve()), hashlib.sha256(raw).hexdigest())

    @property
    def hotwords(self) -> str:
        return ', '.join(self.terms)

    def for_language(self, language: str | None) -> str | None:
        # Auto gets unbiased language-detection windows first; apply only after lock.
        return self.hotwords if language == self.language else None

    def validate_tokens(self, model) -> int:
        count = len(model.hf_tokenizer.encode(' ' + self.hotwords, add_special_tokens=False).ids)
        limit = min(MAX_HINT_TOKENS, model.max_length // 2 - 1)
        if count > limit:
            raise ValueError(f'course vocabulary uses {count} hint tokens; limit={limit}; shorten it')
        return count

    def metadata(self, token_count: int) -> dict:
        return {'name': self.name, 'language': self.language, 'path': self.path,
                'sha256': self.sha256, 'term_count': len(self.terms), 'hint_tokens': token_count,
                'auto_policy': 'apply only after matching language lock'}
