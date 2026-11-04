"""Plain-text presentation of reported usage; this module makes no API calls."""
from app.i18n import tr as _tr
from decimal import Decimal,InvalidOperation


def usd(value):
    try:
        if not isinstance(value,str) or len(value)>48:return None
        number=Decimal(value)
        if not number.is_finite() or not 0<=number<=Decimal('1000000000000'):return None
        if 0<number<Decimal('0.000000001'):return '<$0.000000001'
        return '$'+format(number,'.9f')
    except InvalidOperation:return None


def usage_text(snapshot):
    usage=snapshot.get('reported_token_usage',{})
    def count(key):
        value=usage.get(key)
        return f'{value:,}' if type(value) is int and value>=0 else '—'
    missing=snapshot.get('attempts_without_usage') or 0
    partial=snapshot.get('attempts_partial_usage',0);pending=snapshot.get('usage_pending',0)
    cost=snapshot.get('cost_estimate') or {}
    low,high=usd(cost.get('low')),usd(cost.get('high'))
    amount=(low if low==high else f'{low}–{high}') if low is not None and high is not None else '—'
    prefix=_tr('已知部分预计') if missing or cost.get('unpriced_attempts',0) else _tr('累计预计')
    short=f"Token {count('total_tokens')} · {prefix} {amount} USD"
    unpriced_provider='source' in cost and cost['source'] is None and not cost.get('pricing_available',False)
    if unpriced_provider:short=f"Token {count('total_tokens')}{_tr(' · 费用未估算')}"
    if missing or partial:short+=_tr(' · 用量不完整')
    elif pending:short+=_tr(' · 请求进行中')
    lines=[f"{_tr('输入 ')}{count('prompt_tokens')}{_tr('\u3000输出 ')}{count('completion_tokens')}{_tr('\u3000总计 ')}{count('total_tokens')} Token",
           f"{_tr('缓存命中 ')}{count('prompt_cache_hit_tokens')}{_tr('\u3000未命中 ')}{count('prompt_cache_miss_tokens')} Token",
           f"{prefix}{_tr('费用（USD）：')}{amount}"]
    if missing:lines.append(f"{missing}{_tr(' 次请求未取得用量，未计入上述金额；不能视为零消耗。')}")
    if partial:lines.append(f"{partial}{_tr(' 次用量字段不全；已报告字段仍计入，缺失字段不按零处理。')}")
    if pending:lines.append(f"{pending}{_tr(' 次请求进行中，结束后更新用量。')}")
    if not usage and not missing and not pending:lines.append(_tr('尚未取得已报告用量。'))
    note_values=cost.get('notes',[]);notes=set(note_values) if isinstance(note_values,list) else set()
    if 'peak_or_holiday_uncertain' in notes or 'request_clock_uncertain' in notes:lines.append(_tr('峰谷时段/节假日未完全核实，费用显示区间。'))
    if 'cache_breakdown_missing' in notes:lines.append(_tr('部分请求缺少缓存明细，按可能的缓存价格区间估算。'))
    if 'price_snapshot_age' in notes:lines.append(_tr('价格快照日期与请求日期相隔较远，请核对最新官方价格。'))
    if unpriced_provider:lines.append(_tr('当前来源暂未配置价格估算，请查看对应平台账单；Token 仍照常统计。'))
    elif cost and not cost.get('pricing_available',False):lines.append(_tr('价格表不可用，无法估算金额；Token 仍照常统计。'))
    checked=cost.get('price_checked_on')
    lines.append(f"{_tr('价格核对日期：')}{checked}{_tr('；按官方价格快照估算，实际扣费以平台账单为准。')}" if checked else
                 _tr('金额以所选平台账单为准。') if unpriced_provider else _tr('开始翻译后显示估算依据；实际扣费以平台账单为准。'))
    return short,'\n'.join(lines)
