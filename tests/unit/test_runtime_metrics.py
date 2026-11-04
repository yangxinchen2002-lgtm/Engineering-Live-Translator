import json
from app.diagnostics.runtime import RuntimeMetrics


def test_metric_percentiles_are_bounded_and_invalid_values_not_zeroed():
    metrics=RuntimeMetrics(3)
    for value in (1.,2.,3.,4.):metrics.add('inference',value)
    for value in (-1.,float('nan'),float('inf'),True):metrics.add('inference',value)
    value=metrics.snapshot()
    assert value['metrics_seconds']['inference']['count']==3
    assert value['metrics_seconds']['inference']['p50']==3.
    assert value['invalid_measurements']==4


def test_core_network_and_qt_samples_are_distinct():
    metrics=RuntimeMetrics()
    metrics.event({'event':'asr_result','inference_seconds':.2,'queue_wait_seconds':.1})
    metrics.event({'event':'transcript','first_preview_for_segment':True,'latency_seconds':2,'state':'candidate'})
    metrics.event({'event':'translation_completed','request_seconds':1,'usage':{'total_tokens':30}})
    metrics.event({'event':'subtitle_translation_first_available','segment_id':1,'revision':2,'audio_end_ns':1_000_000_000,
        'audio_end_to_available_seconds':3})
    record={'segment_id':1,'revision':2,'translated_revision':2,'translated_text':'test-only'}
    metrics.begin_paint(1,'main',record,4_000_000_000)
    assert metrics.painted(1,'main','source',4_050_000_000) is None
    event=metrics.painted(1,'main','translation',4_100_000_000)
    assert event['delivery_seconds']==.1 and event['translation_first_paint_seconds']==3.1
    assert metrics.painted(1,'main','translation',5_000_000_000) is None
    data=metrics.snapshot()['metrics_seconds']
    assert data['source_first_available']['p50']==2 and data['translation_request']['p50']==1
    assert data['translation_first_available']['p50']==3 and data['ui_delivery_main']['p50']==.1
    assert 'test-only' not in json.dumps(metrics.snapshot())


def test_old_translation_revision_never_generates_fake_audio_to_paint_latency():
    metrics=RuntimeMetrics()
    metrics.event({'event':'subtitle_translation_first_available','segment_id':1,'revision':1,'audio_end_ns':1000})
    metrics.begin_paint(1,'overlay',{'segment_id':1,'revision':2,'translated_revision':2,'translated_text':'new'},2000)
    metrics.painted(1,'overlay','source',3000);metrics.painted(1,'overlay','translation',4000)
    assert 'translation_first_paint_overlay' not in metrics.series
    assert metrics.counts['unmatched_translation_paint']==1


def test_original_only_overlay_paints_without_hidden_translation_and_pending_is_bounded():
    metrics=RuntimeMetrics()
    record={'segment_id':1,'revision':1,'translated_text':''}
    for token in range(50):metrics.begin_paint(token,'overlay',record,1000,('source',))
    assert len(metrics.pending)==8
    assert metrics.painted(49,'overlay','source',2000)['valid_delivery']


def test_usage_summary_is_authoritative_and_negative_queue_values_not_reported():
    metrics=RuntimeMetrics();metrics.event({'event':'translation_completed','usage':{'total_tokens':30}})
    metrics.event({'event':'bilingual_summary','token_usage':{'total_tokens':55},'attempts_without_usage':2})
    metrics.event({'event':'translation_queue','pending':1,'active':2,'oldest_wait_seconds':float('nan')})
    data=metrics.snapshot()
    assert data['reported_token_usage']['total_tokens']==55 and data['attempts_without_usage']==2
    assert 'oldest_wait_seconds' not in data['latest']['translation_queue'] and data['cost_usd'] is None


def test_preview_drop_counter_matches_real_scheduler_event_name():
    metrics=RuntimeMetrics()
    metrics.event({'event':'preview_window_skipped','job_id':12})
    assert metrics.snapshot()['events']['preview_window_skipped']==1


def test_authoritative_usage_snapshot_counts_retries_once_and_ignores_stale_revisions():
    from datetime import datetime,timezone
    from app.translation.usage import UsageLedger
    ledger=UsageLedger();metrics=RuntimeMetrics();when=datetime(2026,10,31,tzinfo=timezone.utc)
    metrics.event({'event':'translation_usage',**ledger.snapshot()})
    for _ in range(2):
        metrics.event({'event':'translation_submitted'})
        ledger.record({'prompt_tokens':10,'completion_tokens':5,'total_tokens':15},when,when)
        metrics.event({'event':'translation_usage',**ledger.snapshot()})
        metrics.event({'event':'translation_completed','usage':{'total_tokens':15}})
    metrics.event({'event':'translation_usage',**ledger.snapshot()})
    metrics.event({'event':'translation_usage','usage_revision':0,'token_usage':{}})
    result=metrics.snapshot()
    assert result['reported_token_usage']['total_tokens']==30 and result['usage_attempts']==2
    assert result['usage_pending']==0


def test_forced_exit_marks_unsettled_attempts_unknown_without_losing_known_costs():
    from datetime import datetime,timezone
    from app.translation.usage import UsageLedger
    ledger=UsageLedger();metrics=RuntimeMetrics();when=datetime(2026,10,31,tzinfo=timezone.utc)
    metrics.event({'event':'translation_usage',**ledger.snapshot()})
    metrics.event({'event':'translation_submitted'});metrics.event({'event':'translation_submitted'})
    ledger.record({'prompt_tokens':10,'completion_tokens':5,'total_tokens':15,'prompt_cache_hit_tokens':0},when,when)
    metrics.event({'event':'translation_usage',**ledger.snapshot()})
    assert metrics.snapshot()['usage_pending']==1
    metrics.finish_usage();value=metrics.snapshot()
    assert value['usage_pending']==0 and value['attempts_without_usage']==1 and value['usage_lost_on_exit']==1
    assert value['reported_token_usage']['total_tokens']==15 and not value['cost_estimate']['complete']
    assert value['cost_usd'] is None
