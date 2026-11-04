from dataclasses import asdict,replace
import json
import pytest
from app.languages import LANGUAGE_LABELS,join_source
from app.asr.config import ASRConfig,ROOT
from app.asr.language import LanguagePolicy
from app.asr.types import RATE,Word
from app.subtitles.coordinator import SubtitleCoordinator,sentence_end
from app.subtitles.transcript import language_label,transcript_filename
from app.translation.config import TranslationConfig
from app.translation.glossary import Glossary
from app.translation.prompt import messages
from app.ui.preferences import UISettings
from datetime import datetime

SOURCES={'zh':'这个系统是稳定的。','fr':'Ce système est stable.','ru':'Эта система устойчива.',
         'it':'Questo sistema è stabile.','ko':'이 시스템은 안정적입니다.'}


@pytest.mark.parametrize('language',SOURCES)
def test_fixed_auto_translation_and_transcript_languages(language):
    config=ASRConfig.load(language=language)
    assert LanguagePolicy(config).locked==language
    assert replace(UISettings(),language=language).validate()
    policy=LanguagePolicy(ASRConfig(language='auto'))
    for i in range(1,4):policy.observe(language,.99,i*RATE)
    assert policy.locked==language
    prompt=messages(SOURCES[language],language,[],Glossary([]),TranslationConfig())
    assert json.loads(prompt[1]['content'])['current_source_text']==SOURCES[language]
    label=language_label(language,[language])
    assert label==LANGUAGE_LABELS[language]
    assert f'-{label}-2分钟.txt' in transcript_filename(datetime(2026,11,3),label,2)


def test_all_requested_languages_exist_in_the_installed_model_tokenizer():
    tokenizers=pytest.importorskip('tokenizers')
    tokenizer_path=ROOT/'models/large-v3-turbo/tokenizer.json'
    if not tokenizer_path.exists():pytest.skip('local tokenizer is absent')
    from faster_whisper.tokenizer import Tokenizer
    raw=tokenizers.Tokenizer.from_file(str(tokenizer_path))
    for language,text in SOURCES.items():
        tokenizer=Tokenizer(raw,True,task='transcribe',language=language)
        assert tokenizer.language is not None
        pieces,_=tokenizer.split_to_word_tokens(tokenizer.encode(text))
        assert ''.join(pieces)==text


def test_chinese_units_join_without_spaces_and_korean_keeps_word_spaces():
    assert join_source(['这个','系统','是','稳定的。'],'zh')==SOURCES['zh']
    assert join_source(['이',' 시스템은',' 안정적입니다.'],'ko')==SOURCES['ko']
    c=SubtitleCoordinator(replace(TranslationConfig(),mode='sentence'),lambda *a,**k:None)
    requests=[];c.submit=requests.append
    c.consume(session_id=c.session_id,revision=1,source_language='zh',
        confirmed_words=[asdict(Word(text,i*100,(i+1)*100)) for i,text in enumerate(['这个','系统','是','稳定的。'])],
        candidate_words=[],endpoint=True,stability_reason='endpoint_commit')
    assert requests[0].source_text==SOURCES['zh'] and requests[0].source_language=='zh'


@pytest.mark.parametrize('text,language,ends',[('Mme.','fr',False),('ecc.','it',False),('т.е.','ru',False),
    ('И.','ru',False),('稳定。','zh',True),('안정적입니다.','ko',True),('устойчива.','ru',True)])
def test_new_language_sentence_boundaries(text,language,ends):
    assert sentence_end(text,language)==ends
