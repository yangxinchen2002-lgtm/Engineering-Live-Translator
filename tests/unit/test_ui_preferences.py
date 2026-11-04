from dataclasses import replace
import json
import pytest
from app.ui.preferences import UISettings,PreferencesStore,place_window


@pytest.mark.parametrize('size',[6,8,12,21,72])
def test_font_range_includes_small_and_large_text(size):assert replace(UISettings(),font_size=size).validate()


@pytest.mark.parametrize('change',[{'font_size':5},{'font_size':73},{'visible_segments':0},{'visible_segments':13},
    {'source_color':'red; background:url(secret)'},{'font_family':'bad\nfont'},{'opacity':100},{'version':True},
    {'overlay_width':279},{'overlay_height':119},{'main_geometry':(0,0,0,0)},
    {'translation_mode':'unknown'},{'translation_mode':True},{'focus_mode':1},{'focus_mode':'true'},
    {'save_transcripts':1},{'transcript_directory':'bad\x00path'}])
def test_invalid_settings_rejected(change):
    with pytest.raises(ValueError):replace(UISettings(),**change).validate()


def test_settings_roundtrip_only_contains_preferences(tmp_path):
    store=PreferencesStore(tmp_path/'prefs.json')
    settings=replace(UISettings(),font_size=8,visible_segments=8,focus_mode=True,source='edge',overlay_geometry=(-900,70,600,350))
    store.save(settings)
    assert store.load()==settings
    data=json.loads(store.path.read_text(encoding='utf-8'))
    assert not set(data)&{'api_key','translated_text','source_text','pid','capture','click_through','translation_enabled'}
    assert not list(tmp_path.glob('.elt-settings-*'))


@pytest.mark.parametrize('content',[b'not-json',b'\xff',b'{"api_key":"secret-must-not-leak"}',b'x'*16385])
def test_invalid_file_returns_defaults_without_overwriting_or_disclosing(tmp_path,content):
    path=tmp_path/'prefs.json';path.write_bytes(content);store=PreferencesStore(path)
    assert store.load()==UISettings() and store.error
    assert path.read_bytes()==content and 'secret-must-not-leak' not in store.error


def test_atomic_save_failure_preserves_previous_file(tmp_path,monkeypatch):
    from app.ui import preferences
    store=PreferencesStore(tmp_path/'prefs.json');store.save(UISettings());before=store.path.read_bytes()
    def fail(*args):raise PermissionError('replace unavailable')
    monkeypatch.setattr(preferences.os,'replace',fail)
    with pytest.raises(OSError):store.save(replace(UISettings(),font_size=9))
    assert store.path.read_bytes()==before and store.error and not list(tmp_path.glob('.elt-settings-*'))


def test_geometry_supports_negative_monitor_and_recovers_removed_screen():
    screens=[(0,0,1920,1040),(-1280,0,1280,960)]
    assert place_window((-1100,100,900,360),screens)==(-1100,100,900,360)
    assert place_window((-1100,100,900,360),screens[:1])==(0,100,900,360)
    assert place_window((3000,2000,8000,8000),[(0,0,960,600)])==(0,0,960,600)


def test_geometry_keeps_window_inside_scaled_logical_screen():
    assert place_window((1500,800,900,360),[(0,0,1536,824)])==(636,464,900,360)


def test_existing_preferences_without_mode_load_and_new_mode_is_saved(tmp_path):
    path=tmp_path/'prefs.json';path.write_text('{"version":1,"font_size":12}',encoding='utf-8')
    store=PreferencesStore(path);settings=store.load()
    assert settings.translation_mode=='sentence' and settings.font_size==12 and not store.error
    store.save(replace(settings,translation_mode='preview'))
    assert store.load().translation_mode=='preview'
