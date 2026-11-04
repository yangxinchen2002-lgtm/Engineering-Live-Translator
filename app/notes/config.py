"""Validated, non-secret settings captured with each course-notes request."""
from dataclasses import replace
from pathlib import Path
from app.translation.config import TranslationConfig
from app.translation.providers import provider_info


def request_config(payload):
    provider=payload.get('notes_provider','deepseek');info=provider_info(provider)
    model=payload.get('notes_model',info.models[0])
    base=TranslationConfig.load(Path(__file__).resolve().parents[2]/'config/translation.toml')
    return replace(base,provider=provider,base_url=info.base_url,model=model,
        target_language=payload.get('target_language','zh'),concurrency=1,
        request_timeout_seconds=60.,max_tokens=4096,max_output_chars=16384).validate()
