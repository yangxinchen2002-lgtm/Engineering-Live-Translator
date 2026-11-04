"""Language boundaries: interface text, translation target, and local speech."""
import ast
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import pytest

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from app.i18n import set_language,tr,english_catalogue
from app.translation.config import TranslationConfig
from app.translation.glossary import Glossary,Term
from app.translation.prompt import prepare_messages

ROOT=Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def reset_language():
    set_language('zh')
    yield
    set_language('zh')


@pytest.mark.parametrize('target',['zh','en'])
@pytest.mark.parametrize('source',['de','en','ja','zh','fr','ru','it','ko'])
def test_prompt_target_is_independent_of_source_and_bounded(target,source):
    config=replace(TranslationConfig(),target_language=target).validate()
    text='The matrix is not invertible.'
    messages,stats=prepare_messages(text,source,[],Glossary([]),config)
    body=json.loads(messages[1]['content'])
    assert body['current_source_text']==text and body['source_language']==source
    assert ('faithfully into English' in messages[0]['content'])==(target=='en')
    assert sum(len(m['content']) for m in messages)<=config.max_prompt_chars


def test_target_validation_and_glossary_do_not_feed_chinese_targets_to_english_prompt():
    with pytest.raises(ValueError):replace(TranslationConfig(),target_language='fr').validate()
    glossary=Glossary([Term('Eigenwert','特征值','Mathematics','','de'),
        Term('eigenvalue','特征值','Mathematics','','en'),Term('Sonderbegriff','自定义词','Mathematics','','de')])
    english=glossary.relevant('Eigenwert Sonderbegriff','de','',12,2400,target_language='en')
    assert len(english)==1 and english[0]['target_translation']=='eigenvalue'
    chinese=glossary.relevant('Eigenwert Sonderbegriff','de','',12,2400)
    assert [t['target_translation'] for t in chinese]==['自定义词','特征值']


def test_qwen_english_generation_uses_actual_language_and_english_instruction():
    from app.speech.runtime import SpeechEngine
    calls=[]
    model=SimpleNamespace(generate_custom_voice=lambda **options:(calls.append(options) or [[0.,.1,.2]],24000))
    engine=SpeechEngine.__new__(SpeechEngine)
    engine.model=model;engine.fast=False;engine.language='en';engine.model_size='1.7B'
    chunks=list(engine.generate('The matrix is not invertible.','aiden'))
    assert calls[0]['language']=='English' and calls[0]['speaker']=='aiden'
    assert 'university lecturer' in calls[0]['instruct'] and not re.search('[\u3400-\u9fff]',calls[0]['instruct'])
    assert chunks[0][1]==24000
    engine.model_size='0.6B';list(engine.generate('A second sentence.','ryan'))
    assert 'instruct' not in calls[1]


def test_windows_english_engine_passes_language_and_matching_voice(monkeypatch):
    from app.speech import system
    monkeypatch.setattr('app.web_follow.speech.voices_for',lambda language:[{'id':2,'label':'English'}] if language=='en' else [])
    calls=[]
    monkeypatch.setattr(system,'synthesize_pcm',lambda text,index,language:(calls.append((text,index,language)) or b'\x00\x40'*17000))
    engine=system.SystemSpeechEngine(2,language='en');list(engine.generate('Hello.'))
    assert calls==[('Hello.',2,'en')] and engine.info['language']=='en'


@pytest.fixture
def gui(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.ui.controller import BackendController
    monkeypatch.setattr(BackendController,'refresh_processes',lambda self:None)
    monkeypatch.setattr(BackendController,'refresh_web_voices',lambda *a:None)
    return QApplication.instance() or QApplication([])


def test_english_gui_language_and_translation_target_survive_serialization(gui,tmp_path,monkeypatch):
    from app.ui.preferences import PreferencesStore,UISettings
    from app.ui.window import MainWindow
    from app.web_follow.desktop import configuration
    from app.ui import controller
    store=PreferencesStore(tmp_path/'prefs.json');store.save(UISettings(ui_language='en',target_language='en'))
    model=tmp_path/'model';model.mkdir();(model/'model.bin').touch()
    monkeypatch.setattr(controller.ASRConfig,'load',lambda *a,**k:SimpleNamespace(model=str(model)))
    monkeypatch.setattr(controller,'OwnerJob',lambda:SimpleNamespace(name='Local\\ELT.Test',close=lambda:None))
    w=MainWindow(preferences=store);gui.processEvents();w.controller.process.start=lambda:None
    try:
        assert w.translate_check.text()=='Enable translation'
        assert w.target_language.currentData()=='en' and w.ui_language.currentData()=='en'
        assert w.speech_config().language=='en'
        w.capture_mode.setCurrentIndex(w.capture_mode.findData('web'))
        w.translate_check.setChecked(False);w.start_capture()
        options,_,_=configuration(w.controller.pending_command)
        assert options['target_language']=='en' and options['ui_language']=='en'
        assert not w.target_language.isEnabled()
        assert w.settings_snapshot().target_language=='en'
    finally:w.controller.running=False;w.close();gui.processEvents()


def test_interface_translation_never_changes_subtitle_content(gui,tmp_path):
    from app.ui.preferences import PreferencesStore,UISettings
    from app.ui.window import MainWindow
    store=PreferencesStore(tmp_path/'prefs.json');store.save(UISettings(ui_language='en'))
    w=MainWindow(preferences=store);gui.processEvents()
    try:
        w.source.set_caption('开始字幕');w.translation.set_caption('这是课程原文，不应变成按钮文字。')
        assert w.source.text()=='开始字幕' and w.translation.text().startswith('这是课程原文')
        assert tr('开始字幕')=='Start subtitles'
    finally:w.close();gui.processEvents()


def test_all_marked_interface_literals_have_english_catalogue_entries():
    catalogue=english_catalogue();missing=[]
    for path in (ROOT/'app').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text('utf-8-sig'))):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='_tr' and node.args and isinstance(node.args[0],ast.Constant):
                value=node.args[0].value
                if isinstance(value,str) and re.search('[\u3400-\u9fff]',value) and value not in catalogue:missing.append((str(path.relative_to(ROOT)),value))
    assert not missing
    assert all(not re.search('[\u3400-\u9fff]',value) for value in catalogue.values())


def test_ui_default_messages_are_translated_when_called_instead_of_cached_at_import(gui):
    from app.ui.overlay import Overlay
    set_language('en');overlay=Overlay()
    try:
        overlay.focus.clear();assert overlay.focus.placeholder.text()=='Waiting for a complete bilingual subtitle…'
        overlay.clear();assert not re.search('[\u3400-\u9fff]',overlay.source.text())
    finally:overlay.close();gui.processEvents()
    for path in (ROOT/'app/ui').glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text('utf-8'))):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                assert not any(isinstance(value,ast.Constant) and isinstance(value.value,str) and re.search('[\u3400-\u9fff]',value.value)
                    for value in [*node.args.defaults,*node.args.kw_defaults]),str(path)


@pytest.mark.parametrize('ui_language',['zh','en'])
def test_english_transcript_uses_correct_target_without_renaming_previous_file_convention(tmp_path,ui_language):
    from tests.unit.test_transcript_writer import writer,record
    set_language(ui_language)
    async def run():
        value,_,_=writer(tmp_path,target_language='en');value.start();value.source_started()
        value.offer(record(translated_text='The eigenvalue is negative.'))
        result=await value.close(source_complete=True);path=Path(result['transcript_path'])
        assert path.name=='2026-10-31-德语-0分钟.txt'
        text=path.read_text('utf-8')
        assert ('英文' if ui_language=='zh' else 'English') in text
        assert 'The eigenvalue is negative.' in text and result['transcript_complete']
    asyncio.run(run())
