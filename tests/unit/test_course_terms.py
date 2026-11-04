from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from app.asr.config import ASRConfig, ROOT
from app.asr.course_terms import CourseTerms, MAX_HINT_TOKENS


def profile(tmp_path, suffix=''):
    path = tmp_path / 'course.toml'
    path.write_text('version=1\nname="Control"\nlanguage="de"\n'
                    'terms=["Eigenwert", "Übertragungsfunktion"]\n' + suffix, encoding='utf-8')
    return path


def test_profile_load_language_guard_and_identity(tmp_path):
    p = profile(tmp_path)
    course = CourseTerms.load(p, 'de')
    assert course.hotwords == 'Eigenwert, Übertragungsfunktion'
    assert course.for_language('de') == course.hotwords
    assert course.for_language(None) is None and course.for_language('en') is None
    assert course.metadata(10)['sha256'] == course.sha256 and len(course.sha256) == 64
    with pytest.raises(ValueError, match='match'):
        CourseTerms.load(p, 'en')
    assert CourseTerms.load(p, 'auto').language == 'de'


@pytest.mark.parametrize('replacement', [
    'version=2', 'version=true', 'language="es"', 'terms=[]',
    'terms=["Kernel", "kernel"]', 'terms=[" "]', 'terms=[3]',
    'terms=["line\\nfeed"]', 'sources="url"',
])
def test_profile_invalid_schema(tmp_path, replacement):
    p = profile(tmp_path)
    lines = p.read_text(encoding='utf-8').splitlines()
    key = replacement.split('=')[0]
    lines = [line for line in lines if not line.startswith(key+'=')]
    p.write_text('\n'.join(lines+[replacement]), encoding='utf-8')
    with pytest.raises(ValueError): CourseTerms.load(p)


def test_profile_file_bound_unknown_key_and_missing(tmp_path):
    with pytest.raises(FileNotFoundError): CourseTerms.load(tmp_path/'absent')
    with pytest.raises(ValueError, match='unknown'): CourseTerms.load(profile(tmp_path, 'typo=1'))
    p = profile(tmp_path)
    p.write_bytes(b' ' * 16_385)
    with pytest.raises(ValueError, match='16 KiB'): CourseTerms.load(p)


def test_profile_token_limit_is_checked_without_silent_truncation(tmp_path):
    course = CourseTerms.load(profile(tmp_path))
    model = SimpleNamespace(max_length=448, hf_tokenizer=SimpleNamespace(
        encode=lambda text, add_special_tokens: SimpleNamespace(ids=list(range(MAX_HINT_TOKENS)))))
    assert course.validate_tokens(model) == MAX_HINT_TOKENS
    model.hf_tokenizer.encode = lambda *a, **k: SimpleNamespace(ids=list(range(MAX_HINT_TOKENS+1)))
    with pytest.raises(ValueError, match='shorten'): course.validate_tokens(model)


def test_profile_term_count_and_character_bounds(tmp_path):
    p=profile(tmp_path)
    header='version=1\nname="Control"\nlanguage="de"\nterms='
    for terms in [[str(i) for i in range(49)],['x'*81]]:
        p.write_text(header+json.dumps(terms),encoding='utf-8')
        with pytest.raises(ValueError): CourseTerms.load(p)


def test_profile_config_relative_path_and_explicit_disable(tmp_path):
    p = tmp_path/'asr.toml'
    p.write_text('[asr]\ncourse_terms="courses/de.toml"', encoding='utf-8')
    assert ASRConfig.load(p).course_terms == str((tmp_path/'courses/de.toml').resolve())
    assert ASRConfig.load(p, course_terms='').course_terms is None
    with pytest.raises(ValueError): replace(ASRConfig(), course_terms=42).validate()
    for lang, stem in [('de','de-firmware'), ('en','en-linear-algebra')]:
        assert CourseTerms.load(ROOT/f'config/courses/{stem}.toml',lang).terms


def test_replay_plan_rejects_incomplete_and_preserves_order(tmp_path):
    from tools.compare_course_terms import replay_windows
    p = tmp_path/'baseline.jsonl'
    rows = [{'event':'asr_result','start_sample':0,'end_sample':16_000,'endpoint':False},
            {'event':'asr_result','start_sample':0,'end_sample':32_000,'endpoint':True},
            {'event':'asr_summary','complete':True,'samples':32_000}]
    p.write_text('\n'.join(json.dumps(r) for r in rows),encoding='utf-8')
    windows = replay_windows(p,32_000)
    assert [(w.start,w.end,w.endpoint) for w in windows] == [(0,16_000,False),(0,32_000,True)]
    rows[-1]['complete'] = False
    p.write_text('\n'.join(json.dumps(r) for r in rows),encoding='utf-8')
    with pytest.raises(ValueError,match='complete'): replay_windows(p,32_000)


def test_holdout_window_plan_keeps_global_sample_coordinates(monkeypatch):
    import numpy as np
    from tools import compare_course_terms as trial
    class VAD:
        def __init__(self,config):self.first=True
        def feed(self,audio):
            if self.first:
                self.first=False
                return [SimpleNamespace(kind='start',sample=0)]
            return []
    monkeypatch.setattr(trial,'SileroStream',VAD)
    plan=trial.new_windows(np.zeros(48_000,np.float32),16_000,48_000,ASRConfig())
    assert [(w.start,w.end,w.endpoint) for w in plan]==[
        (16_000,32_000,False),(16_000,48_000,False),(16_000,48_000,True)]
