"""Japanese text/timestamp behavior; no network calls or model inference."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.asr.config import ASRConfig, ROOT
from app.asr.course_terms import CourseTerms
from app.asr.decoding import segment_words
from app.asr.language import LanguagePolicy
from app.asr.stabilizer import TranscriptStabilizer, render_words
from app.asr.types import RATE, Word
from app.languages import join_source
from app.subtitles.coordinator import SubtitleCoordinator, sentence_end
from app.translation.config import TranslationConfig
from app.translation.glossary import Glossary
from app.translation.prompt import messages
from app.ui.preferences import PreferencesStore, UISettings


def test_fixed_auto_and_persisted_japanese(tmp_path):
    assert ASRConfig.load(language='ja').language == 'ja'
    assert LanguagePolicy(ASRConfig(language='ja')).locked == 'ja'
    policy = LanguagePolicy(ASRConfig(language='auto'))
    for index in range(1, 4):
        assert policy.observe('ja', .95, index * RATE) == (index == 3)
    assert not policy.observe('en', 1., 4 * RATE) and policy.locked == 'ja'
    store = PreferencesStore(tmp_path/'settings.json')
    settings = replace(UISettings(), language='ja')
    store.save(settings)
    assert store.load() == settings


def test_japanese_course_terms_keep_language_guard(tmp_path):
    path = tmp_path/'course.toml'
    path.write_text('version=1\nname="制御"\nlanguage="ja"\nterms=["伝達関数", "固有値"]', encoding='utf-8')
    terms = CourseTerms.load(path, 'ja')
    assert terms.for_language('ja') == '伝達関数, 固有値'
    assert terms.for_language(None) is None
    with pytest.raises(ValueError, match='match'):
        CourseTerms.load(path, 'de')


def test_installed_model_tokenizer_supports_japanese_without_inference():
    tokenizers = pytest.importorskip('tokenizers')
    from faster_whisper.tokenizer import Tokenizer
    path = ROOT/'models/large-v3-turbo/tokenizer.json'
    if not path.is_file():
        pytest.skip('local model tokenizer is not installed')
    raw = tokenizers.Tokenizer.from_file(str(path))
    tokenizer = Tokenizer(raw, True, task='transcribe', language='ja')
    assert tokenizer.language == raw.token_to_id('<|ja|>') is not None
    text = '制御系では PID controller を使います。'
    pieces, _ = tokenizer.split_to_word_tokens(tokenizer.encode(text))
    assert ''.join(pieces) == text
    assert join_source(pieces, 'ja') == text


def test_shared_timestamps_keep_particles_punctuation_and_short_pieces():
    def piece(text, start, end):
        return SimpleNamespace(word=text, start=start, end=end)
    segments = [SimpleNamespace(words=[piece('こ',0,0), piece('れ',0,.1), piece('は',.1,.1),
        piece('行列',.1,.2), piece('で',.2,.21), piece('す',.21,.22), piece('。',.22,.22)])]
    units = segment_words(segments, 0, RATE, 'ja')
    assert render_words(units, 'ja') == 'これは行列です。'
    assert all(a.end < b.end for a, b in zip(units, units[1:]))
    stabilizer = TranscriptStabilizer(tail_seconds=.01)
    first = stabilizer.update(units[:2], RATE, endpoint=True, language='ja')
    second = stabilizer.update(units, 2 * RATE, endpoint=True, language='ja')
    assert render_words(first.committed + second.committed, 'ja') == 'これは行列です。'
    assert not stabilizer.update(units, 3 * RATE, endpoint=True, language='ja').committed
    # Spaces inside a Japanese/English code-switch belong to the model output.
    assert join_source(['この', ' PID', ' controller', 'を使います。'], 'ja') == 'この PID controllerを使います。'
    assert render_words([Word(' The',0,1), Word(' system.',1,2)], 'en') == 'The system.'


def test_all_zero_alignment_reports_failure_instead_of_losing_text():
    segments = [SimpleNamespace(words=[SimpleNamespace(word='行列',start=0,end=0)])]
    with pytest.raises(RuntimeError, match='incomplete'):
        segment_words(segments, 0, RATE, 'ja')


@pytest.mark.parametrize('text,expected', [('です。',True), ('安定ですか？',True), ('「例です。」',True),
    ('例です。』',True), ('3.14',False), ('行列、',False)])
def test_japanese_sentence_end(text, expected):
    assert sentence_end(text, 'ja') is expected


@pytest.mark.parametrize('mode', ['preview', 'sentence'])
def test_japanese_live_candidate_sentence_final_and_stale_response(mode):
    requests = []
    c = SubtitleCoordinator(replace(TranslationConfig(), mode=mode), lambda *a, **k: None, realtime=False)
    c.submit = requests.append
    def feed(revision, confirmed, candidate, endpoint=False):
        c.consume(session_id=c.session_id, revision=revision, source_language='ja',
            confirmed_words=[asdict(w) for w in confirmed], candidate_words=[asdict(w) for w in candidate],
            endpoint=endpoint, stability_reason='local_agreement')
    words = [Word(text, index*1000, (index+1)*1000) for index, text in enumerate(['この','行列','は','非対称','です。'])]
    feed(1, words[:4], words[4:])
    assert c.records[1].source_text == 'この行列は非対称' and c.records[1].candidate_text == 'です。'
    assert len(requests) == (1 if mode == 'preview' else 0)
    old = requests[0] if requests else None
    feed(2, words[4:], [], True)
    assert c.records[1].source_text == 'この行列は非対称です。'
    request = requests[-1]
    assert request.source_language == 'ja' and request.source_closed
    assert c.begin(request, 'attempt') and c.complete(request, 'attempt', '这个矩阵不对称。')
    if old:
        assert not c.complete(old, 'old', '旧译文')
    assert c.records[1].state == 'final'


def test_japanese_character_bound_preserves_all_text_without_treating_tokens_as_words():
    requests = []
    c = SubtitleCoordinator(replace(TranslationConfig(), mode='sentence', max_source_words=4, max_source_chars=80),
        lambda *a, **k: None, realtime=False)
    c.submit = requests.append
    text = 'あ'*100 + '。'
    c.consume(session_id=c.session_id,revision=1,source_language='ja',
        confirmed_words=[dict(text=char,start=i*100,end=(i+1)*100) for i,char in enumerate(text)],
        candidate_words=[],endpoint=True,stability_reason='endpoint_commit')
    assert [len(request.source_text) for request in requests] == [80,21]
    assert ''.join(request.source_text for request in requests) == text


def test_japanese_glossary_matches_particles_and_prompt_keeps_original(tmp_path):
    path = tmp_path/'terms.json'
    path.write_text(json.dumps({'version':1,'entries':[
        dict(source_term='固有値',target_translation='特征值',domain='mathematics',context_note='',source_language='ja'),
        dict(source_term='rank',target_translation='秩',domain='mathematics',context_note='',source_language='en')
    ]}, ensure_ascii=False), encoding='utf-8')
    glossary = Glossary.load(path)
    text = '固有値が負なら、この系は安定です。'
    prompt = messages(text, 'ja', [], glossary, TranslationConfig())
    data = json.loads(prompt[1]['content'])
    assert '日语' in prompt[0]['content']
    assert data['source_language'] == 'ja' and data['current_source_text'] == text
    assert [term['target_translation'] for term in data['relevant_terminology']] == ['特征值']
    assert not glossary.relevant(text, 'de', '', 12, 2400)


def test_cli_passes_japanese_without_requesting_credentials(monkeypatch):
    from app.main import main
    from app.translation import cli
    seen = []
    monkeypatch.setattr(cli, 'translate', lambda args: seen.append(args) or 0)
    assert main(['translate-text','--language','ja','--text','行列は正則です。']) == 0
    assert main(['translate-file','--language','ja','--input','sample.wav','--source-only']) == 0
    assert all(args.language == 'ja' for args in seen)
