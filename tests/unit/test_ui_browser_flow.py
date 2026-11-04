import os
import threading
import time
from types import SimpleNamespace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest,QSignalSpy
from app.audio.processes import ProcessInfo
from app.ui import controller as module
from app.ui.window import MainWindow


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('title,executable',[('VLC','vlc.exe'),('Chrome','chrome.exe'),('Edge','msedge.exe'),('播放器','player.exe')])
def test_unified_app_picker_controls_scope_readiness_and_exit(app,title,executable):
    window=MainWindow()
    assert window.controller.source_kind=='sessions' and '标签页' in window.source_hint.text()
    target=ProcessInfo(42,executable,'C:/'+executable,100,display_name=title,audio_state='active')
    window.processes_ready([target],[])
    assert window.target==target and window.start_button.isEnabled()
    assert title in window.process_combo.currentText()
    window.backend_event({'event':'asr_model_ready','device':'cuda'})
    assert f'连接 {title}' in window.notice.text()
    window.backend_event({'event':'audio_source_ready','source':'sessions','signal':'unverified'})
    assert f'继续播放 {title}' in window.notice.text()
    window.backend_event({'event':'bilingual_source_error','message':'target_exited_select_again'})
    assert f'{title} 已退出' in window.notice.text()
    assert not window.controller.running
    window.close();app.processEvents()


def test_source_cannot_change_while_session_is_running(app):
    controller=module.BackendController();controller.running=True
    try:
        with pytest.raises(RuntimeError,match='停止'):controller.set_source_kind('chrome')
        assert controller.source_kind=='sessions'
    finally:controller.running=False;controller.cleanup_idle()


@pytest.mark.parametrize('old_fails',[False,True])
def test_late_discovery_for_old_source_is_discarded_and_new_source_refreshed(app,monkeypatch,old_fails):
    started=threading.Event();release=threading.Event();calls=[]
    target=ProcessInfo(42,'chrome.exe','C:/chrome.exe',100)
    class Selector:
        def discover(self,source):
            calls.append(source)
            if source=='vlc':
                started.set();release.wait(2)
                if old_fails:raise PermissionError('old scan failed')
                return [ProcessInfo(1,'vlc.exe','C:/vlc.exe',50)],[]
            return [target],[]
    monkeypatch.setattr(module,'ProcessSelector',Selector)
    controller=module.BackendController();controller.source_kind='vlc'
    events=QSignalSpy(controller.processes_ready);errors=QSignalSpy(controller.problem)
    try:
        controller.refresh_processes();assert started.wait(1)
        controller.set_source_kind('chrome');release.set()
        deadline=time.monotonic()+3
        while (len(calls)<2 or events.count()<2) and time.monotonic()<deadline:QTest.qWait(20)
        assert calls==['vlc','chrome'] and events.count()==2
        assert events.at(0)[0]==[] and events.at(1)[0]==[target]
        assert errors.count()==0
    finally:release.set();controller.cleanup_idle()


@pytest.mark.parametrize('source,executable',[('chrome','chrome.exe'),('edge','msedge.exe'),('sessions','player.exe')])
@pytest.mark.parametrize('translation_mode',['preview','sentence'])
@pytest.mark.parametrize('language',['en','ja'])
def test_gui_passes_browser_source_to_real_backend_command(app,monkeypatch,tmp_path,source,executable,translation_mode,language):
    target=ProcessInfo(42,executable,'C:/'+executable,100)
    monkeypatch.setattr(module,'ProcessSelector',lambda:SimpleNamespace(inspect=lambda pid:target))
    helper=tmp_path/'native/build/Release/elt_capture.exe';helper.parent.mkdir(parents=True);helper.touch()
    model=tmp_path/'model';model.mkdir();(model/'model.bin').touch()
    monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module.ASRConfig,'load',lambda *args,**kwargs:SimpleNamespace(model=str(model)))
    class Job:
        name='Local\\ELT.Gui.test-only'
        def close(self):pass
    monkeypatch.setattr(module,'OwnerJob',Job)
    class Process:
        def readAllStandardOutput(self):return b''
        def readAllStandardError(self):return b''
        def setProcessEnvironment(self,value):self.env=value
        def setWorkingDirectory(self,value):self.cwd=value
        def setProgram(self,value):self.program=value
        def setArguments(self,value):self.arguments=value
        def start(self):self.started=True
    controller=module.BackendController();controller.source_kind=source;process=Process();controller.process=process
    try:
        glossary=tmp_path/'selected-terms.json'
        controller.telemetry.event({'event':'translation_completed','usage':{'total_tokens':500}})
        controller.start(target,language,False,60,glossary=glossary,translation_mode=translation_mode,transcript_directory=tmp_path)
        assert process.started and controller.running
        assert controller.telemetry.snapshot()['reported_token_usage']=={} and controller.telemetry.snapshot()['usage_pending']==0
        assert process.arguments[process.arguments.index('--source')+1]==source
        assert process.arguments[process.arguments.index('--language')+1]==language
        assert '--source-only' in process.arguments
        assert process.arguments[process.arguments.index('--glossary')+1]==str(glossary)
        assert process.arguments[process.arguments.index('--expected-created')+1]=='100'
        assert process.arguments[process.arguments.index('--translation-mode')+1]==translation_mode
        assert process.arguments[process.arguments.index('--transcript-directory')+1]==str(tmp_path)
    finally:controller.running=False;controller.cleanup_idle()


def test_wrong_app_family_is_rejected_before_backend_start(app,monkeypatch):
    target=ProcessInfo(42,'msedge.exe','C:/msedge.exe',100)
    monkeypatch.setattr(module,'ProcessSelector',lambda:SimpleNamespace(inspect=lambda pid:target))
    controller=module.BackendController();controller.source_kind='chrome'
    try:
        with pytest.raises(ValueError,match='进程已改变'):controller.start(target,'en',False,60)
        assert not controller.running
    finally:controller.cleanup_idle()


def test_mixer_source_displays_application_metadata_and_identity_without_auto_capture(app):
    window=MainWindow()
    from app.asr.config import ROOT
    target=ProcessInfo(42,'player.exe',str(ROOT/'ELT.exe'),100,
        display_name='播放器',audio_state='active',audio_sessions=2)
    try:
        window.processes_ready([target],[])
        assert window.target==target and '播放器' in window.process_combo.currentText()
        assert '活动' in window.process_combo.currentText() and '音量合成器' in window.source_hint.text()
        assert not window.controller.running and window.start_button.isEnabled()
        window.backend_event({'event':'audio_source_ready'})
        assert '播放器' in window.notice.text()
        window.processes_ready([ProcessInfo(42,'player.exe',target.path,101,display_name='重新启动')],[])
        assert window.target.created==101
    finally:window.close();app.processEvents()


def test_audio_picker_has_no_family_filter_and_refresh_uses_windows_sessions(app,monkeypatch):
    from PySide6.QtWidgets import QComboBox
    scans=[]
    monkeypatch.setattr(module.BackendController,'refresh_processes',lambda self:scans.append(self.source_kind))
    window=MainWindow()
    try:
        assert not hasattr(window,'source_combo') and not hasattr(window,'open_vlc_button')
        pickers=[box for box in window.findChildren(QComboBox) if box.accessibleName()=='音频来源应用']
        assert pickers==[window.process_combo]
        window.refresh_button.click();assert scans==['sessions']
        window.processes_ready([],[])
        assert not window.start_button.isEnabled() and '播放一下声音' in window.notice.text()
        window.capture_mode.setCurrentIndex(window.capture_mode.findData('web'))
        assert window.process_combo.isHidden() and window.refresh_button.isHidden()
        window.capture_mode.setCurrentIndex(window.capture_mode.findData('audio'))
        assert not window.process_combo.isHidden() and not window.refresh_button.isHidden()
        assert window.controller.source_kind=='sessions' and '选择应用' in window.guide.text()
    finally:window.close();app.processEvents()


@pytest.mark.parametrize('old_source',['vlc','chrome','edge','sessions'])
def test_legacy_saved_source_does_not_reinstate_filter_or_reset_preferences(app,monkeypatch,tmp_path,old_source):
    from dataclasses import replace
    from app.ui.preferences import PreferencesStore,UISettings
    monkeypatch.setattr(module.BackendController,'refresh_processes',lambda self:None)
    store=PreferencesStore(tmp_path/'settings.json')
    store.save(replace(UISettings(),source=old_source,language='ja',font_size=12,speech_volume=37))
    original=store.path.read_bytes();window=MainWindow(preferences=store)
    try:
        saved=window.settings_snapshot()
        assert window.controller.source_kind==saved.source=='sessions'
        assert saved.language=='ja' and saved.font_size==12 and saved.speech_volume==37
        assert store.path.read_bytes()==original and not store.error
        assert not window.controller.running
    finally:window.close();app.processEvents()
