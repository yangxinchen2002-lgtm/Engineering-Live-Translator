"""Source languages shared by recognition, translation, settings and exports."""
from collections.abc import Iterable

LANGUAGE_LABELS = {'de': '德语', 'en': '英语', 'ja': '日语', 'zh': '中文',
                   'fr': '法语', 'ru': '俄语', 'it': '意大利语', 'ko': '韩语'}
SOURCE_LANGUAGES = tuple(LANGUAGE_LABELS)
ASR_LANGUAGES = (*SOURCE_LANGUAGES, 'auto')
TARGET_LANGUAGES = ('zh','en')
NO_SPACE_LANGUAGES = frozenset({'ja', 'zh'})


def join_source(parts: Iterable[str], language: str | None = None, *, strip: bool = True) -> str:
    """Preserve Chinese/Japanese decoder spacing without inserting word spaces."""
    if language in NO_SPACE_LANGUAGES:
        text = ''.join(parts)
        return text.strip() if strip else text
    return ' '.join(part.strip() for part in parts if part.strip()).strip()
