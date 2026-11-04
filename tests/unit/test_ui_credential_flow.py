import os
import time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtTest import QSignalSpy,QTest
from PySide6.QtWidgets import QApplication
from app.translation.credentials import CredentialStoreError
from app.ui import controller as module


def wait_for(spy):
    deadline=time.monotonic()+3
    while not spy.count() and time.monotonic()<deadline:QTest.qWait(20)
    assert spy.count()==1
    return spy.at(0)


@pytest.mark.parametrize('error,expected',[
    (ValueError('private-sentinel-key'),'格式'),
    (CredentialStoreError('write',5),'错误码 5'),
    (RuntimeError('private-sentinel-key'),'组件'),
])
def test_worker_failure_reaches_gui_without_secret(monkeypatch,error,expected):
    app=QApplication.instance() or QApplication([])
    controller=module.BackendController()
    def fail(value):raise error
    monkeypatch.setattr(module,'store_credential',fail)
    spy=QSignalSpy(controller.credential_saved)
    try:
        controller.save_credential('private-sentinel-key')
        success,message=wait_for(spy)
        assert success is False and expected in message
        assert 'private-sentinel-key' not in message
    finally:controller.cleanup_idle()


def test_success_reports_saved_status_and_readback_failure_is_not_mislabelled(monkeypatch):
    app=QApplication.instance() or QApplication([])
    controller=module.BackendController()
    monkeypatch.setattr(module,'store_credential',lambda value:{'stored':True})
    monkeypatch.setattr(module,'manage_credential',lambda action:{'available':True,'source':'windows_credential'})
    spy=QSignalSpy(controller.credential_saved)
    try:
        controller.save_credential('test-only-value')
        assert wait_for(spy)[0] is True
        def read_failure(action):raise CredentialStoreError('read',5)
        monkeypatch.setattr(module,'manage_credential',read_failure)
        after=QSignalSpy(controller.credential_saved)
        controller.save_credential('test-only-value')
        success,message=wait_for(after)
        assert success is False and '已写入' in message and '错误码 5' in message
        assert '格式' not in message
    finally:controller.cleanup_idle()
