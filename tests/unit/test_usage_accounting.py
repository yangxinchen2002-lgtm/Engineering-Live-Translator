from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
from pathlib import Path
import pytest
from app.translation.usage import PriceCard,UsageLedger,peak_possible,read_usage
from app.ui.usage import usage_text,usd

SATURDAY=datetime(2026,10,31,2,tzinfo=timezone.utc)
USAGE={'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100,
       'prompt_cache_hit_tokens':800,'prompt_cache_miss_tokens':200}


def record(value=USAGE,*,start=SATURDAY,end=None):
    ledger=UsageLedger();ledger.record(value,start,end or start+timedelta(seconds=2));return ledger


def test_official_rate_card_and_exact_cache_accounting_use_decimal_usd():
    snapshot=record().snapshot();cost=snapshot['cost_estimate']
    assert snapshot['usage_complete'] and snapshot['usage_attempts']==1
    assert cost['currency']=='USD' and cost['price_checked_on']=='2026-10-31'
    assert Decimal(cost['low'])==Decimal('0.0000924')==Decimal(cost['high'])
    assert cost['complete'] and snapshot['cost_usd']==cost['low']


def test_weekday_peak_holiday_uncertainty_is_range_not_an_exact_charge():
    value=record(start=datetime(2026,11,2,2,tzinfo=timezone.utc)).snapshot()
    cost=value['cost_estimate']
    assert Decimal(cost['low'])==Decimal('0.0000924') and Decimal(cost['high'])==Decimal('0.0001848')
    assert 'peak_or_holiday_uncertain' in cost['notes'] and value['cost_usd'] is None


@pytest.mark.parametrize('day,hour,expected',[(2,0,False),(2,1,True),(2,3,True),(2,4,False),
    (2,6,True),(2,9,True),(2,10,False),(7,2,False),(8,7,False)])
def test_utc_peak_boundaries_and_weekends(day,hour,expected):
    start=datetime(2026,11,day,hour,tzinfo=timezone.utc)
    assert peak_possible(start,start+timedelta(seconds=1)) is expected


def test_crossing_rate_boundary_or_invalid_clock_never_claims_exact_off_peak():
    start=datetime(2026,11,2,0,59,59,tzinfo=timezone.utc)
    assert peak_possible(start,start+timedelta(seconds=2))
    assert peak_possible(start,start-timedelta(seconds=1))
    assert peak_possible(start.replace(tzinfo=None),start.replace(tzinfo=None))
    assert peak_possible(start,start+timedelta(hours=3))


def test_nested_cache_alias_and_derived_miss_total_are_consistent():
    value=read_usage({'prompt_tokens':100,'completion_tokens':10,'prompt_tokens_details':{'cached_tokens':80}})
    assert value['prompt_cache_hit_tokens']==80 and value['prompt_cache_miss_tokens']==20 and value['total_tokens']==110
    assert read_usage({'prompt_cache_hit_tokens':2,'prompt_cache_miss_tokens':3})['prompt_tokens']==5


@pytest.mark.parametrize('value',[None,{'total_tokens':-1},{'prompt_tokens':True},
    {'total_tokens':1.5},{'prompt_tokens':2,'prompt_cache_hit_tokens':3},
    {'prompt_tokens':2,'completion_tokens':3,'total_tokens':6},
    {'prompt_tokens':3,'prompt_cache_hit_tokens':1,'prompt_cache_miss_tokens':1},
    {'prompt_cache_hit_tokens':1,'prompt_tokens_details':{'cached_tokens':2}}])
def test_invalid_provider_usage_is_not_silently_zeroed(value):
    with pytest.raises(ValueError):read_usage(value)
    snapshot=record(value).snapshot()
    assert snapshot['attempts_without_usage']==1 and not snapshot['usage_complete']
    assert snapshot['cost_estimate']['low'] is None


def test_cache_breakdown_missing_has_valid_bounds_without_invented_cache_counts():
    value=record({'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100}).snapshot()
    cost=value['cost_estimate']
    assert Decimal(cost['low'])==Decimal('0.000063') and Decimal(cost['high'])==Decimal('0.00021')
    assert 'prompt_cache_hit_tokens' not in value['token_usage'] and 'cache_breakdown_missing' in cost['notes']


def test_partial_and_missing_attempts_keep_known_total_and_mark_unpriced_portion():
    ledger=record();ledger.record({'total_tokens':7},SATURDAY,SATURDAY);ledger.record(None,SATURDAY,SATURDAY)
    value=ledger.snapshot()
    assert value['token_usage']['total_tokens']==1107 and value['usage_attempts']==3
    assert value['attempts_partial_usage']==1 and value['attempts_without_usage']==1
    assert not value['cost_estimate']['complete'] and value['cost_estimate']['unpriced_attempts']==2
    assert Decimal(value['cost_estimate']['low'])==Decimal('0.0000924')


def test_explicit_zero_usage_is_valid_but_absence_is_unknown():
    value=record({'prompt_tokens':0,'completion_tokens':0,'total_tokens':0,'prompt_cache_hit_tokens':0}).snapshot()
    assert value['usage_complete'] and Decimal(value['cost_usd'])==0
    assert UsageLedger().snapshot()['cost_usd'] is None


def test_long_course_totals_are_not_capped_by_512_metric_samples():
    ledger=UsageLedger()
    for _ in range(1200):ledger.record(USAGE,SATURDAY,SATURDAY)
    snapshot=ledger.snapshot()
    assert snapshot['usage_attempts']==1200 and snapshot['token_usage']['total_tokens']==1320000
    assert Decimal(snapshot['cost_usd'])==Decimal('0.11088')


def test_invalid_or_unavailable_price_table_preserves_usage(tmp_path,monkeypatch):
    data=json.loads(Path('app/translation/deepseek_pricing.json').read_text(encoding='utf-8'))
    data['off_peak']['cache_hit']='NaN';path=tmp_path/'prices.json';path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(ValueError):PriceCard.load(path)
    def unavailable(*args):raise OSError('test-only unavailable price card')
    monkeypatch.setattr(PriceCard,'load',unavailable)
    value=record().snapshot()
    assert value['token_usage']['total_tokens']==1100 and value['usage_complete']
    assert not value['cost_estimate']['pricing_available'] and value['cost_usd'] is None


def test_old_price_snapshot_is_explicit_and_money_format_does_not_hide_small_nonzero():
    value=record(start=SATURDAY+timedelta(days=40)).snapshot()
    assert 'price_snapshot_age' in value['cost_estimate']['notes']
    assert usd('0.000000003')=='$0.000000003'
    assert usd('0.0000000001')=='<$0.000000001'
    assert usd('NaN') is None and usd('-1') is None and usd('1E999999') is None


def test_presentation_separates_reported_totals_estimates_unknown_and_inflight():
    value=record().snapshot()
    snapshot={'reported_token_usage':value['token_usage'],'cost_estimate':value['cost_estimate'],
              'attempts_without_usage':1,'attempts_partial_usage':1,'usage_pending':2}
    short,detail=usage_text(snapshot)
    assert '1,100' in short and '已知部分' in short and '不完整' in short
    assert '输入 1,000' in detail and '缓存命中 800' in detail and '不能视为零消耗' in detail
    assert '2 次请求进行中' in detail and '账单' in detail
