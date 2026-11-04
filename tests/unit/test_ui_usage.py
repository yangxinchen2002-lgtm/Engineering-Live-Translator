import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from datetime import datetime,timezone
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from app.ui.window import MainWindow,STYLE
from app.translation.usage import UsageLedger

WHEN=datetime(2026,10,31,tzinfo=timezone.utc)
USAGE={'prompt_tokens':1000,'completion_tokens':100,'total_tokens':1100,
       'prompt_cache_hit_tokens':800,'prompt_cache_miss_tokens':200}


@pytest.fixture
def window(monkeypatch):
    from app.ui import controller
    monkeypatch.setattr(controller,'manage_credential',lambda action:{'available':False,'source':'unavailable'})
    app=QApplication.instance() or QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    value=MainWindow();value.show();app.processEvents()
    yield value
    if value.performance_dialog:value.performance_dialog.close()
    value.close();app.processEvents()


def send(window,event,**data):window.controller.accept_event({'event':event,**data})


def test_footer_and_performance_details_use_same_authoritative_usage(window):
    ledger=UsageLedger();send(window,'translation_usage',**ledger.snapshot());send(window,'translation_submitted')
    assert '进行中' in window.usage_summary.text()
    ledger.record(USAGE,WHEN,WHEN);send(window,'translation_usage',**ledger.snapshot())
    send(window,'translation_completed',usage=USAGE)
    assert '1,100' in window.usage_summary.text() and '$0.000092400' in window.usage_summary.text()
    send(window,'translation_usage',**ledger.snapshot())
    window.show_performance();detail=window.performance_dialog.usage_info.text()
    assert '输入 1,000' in detail and '输出 100' in detail and '缓存命中 800' in detail
    assert '2026-10-31' in detail and '平台账单' in detail
    assert not window.controller.running and not window.overlay.isVisible()


def test_unknown_usage_and_forced_exit_are_visible_and_do_not_reset_known_amount(window):
    ledger=UsageLedger();send(window,'translation_usage',**ledger.snapshot())
    send(window,'translation_submitted');ledger.record(USAGE,WHEN,WHEN);send(window,'translation_usage',**ledger.snapshot())
    send(window,'translation_submitted');window.controller.telemetry.finish_usage();window.capture_finished(1,False)
    assert '不完整' in window.usage_summary.text() and '已知部分' in window.usage_summary.text()
    assert '$0.000092400' in window.usage_summary.text()
    assert '不能视为零消耗' in window.usage_summary.toolTip()


def test_no_calls_do_not_display_a_fake_zero_bill_and_price_unavailable_keeps_tokens(window):
    assert '预计 —' in window.usage_summary.text()
    send(window,'translation_usage',usage_revision=1,usage_attempts=1,token_usage={'total_tokens':25},
         attempts_without_usage=0,attempts_partial_usage=1,cost_estimate={'currency':'USD','low':None,'high':None,
         'unpriced_attempts':1,'pricing_available':False,'notes':[]})
    assert '25' in window.usage_summary.text() and '预计 —' in window.usage_summary.text()
    assert '价格表不可用' in window.usage_summary.toolTip()
