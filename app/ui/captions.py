"""Display policy shared by the list and focus views; never changes backend state."""
from app.i18n import tr as _tr

def final_translation(record):
    return bool(record.get('state')=='final' and record.get('translated_text','').strip()
                and record.get('translated_revision')==record.get('revision'))


def translation_failed(record):
    status=record.get('translation_status')
    return bool(status and status not in ('waiting','waiting_sentence','waiting_previous','pending','partial','streaming','ready','retrying'))


def translation_pending(record):
    """Closed source still has a useful in-flight, queued or retrying request."""
    return bool(record.get('source_closed') and record.get('source_text','').strip() and not final_translation(record)
                and (not translation_failed(record) or record.get('translation_retry_pending',False)))


def reading_hold_ms(record):
    # Only used after waiting for a late translation, not on ordinary updates.
    return max(1500,min(8000,sum(c.isalnum() for c in record.get('translated_text',''))*90))


def translation_caption(record):
    if record.get('translation_status')=='waiting_previous':return _tr('前句处理中 · 译文将按原文顺序显示')
    if translation_failed(record) and not final_translation(record):return _tr('译文暂不可用 · 原文已保留')
    if record.get('translated_text'):return record['translated_text']
    if record.get('translation_status')=='waiting_sentence':return _tr('等待整句结束后翻译…')
    return _tr('等待翻译…')
