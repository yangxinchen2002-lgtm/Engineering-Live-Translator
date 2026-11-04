"""Official text API identities; no credentials or user-configurable hosts."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Provider:
    label:str
    base_url:str
    models:tuple[str,...]
    environment:str
    credential_name:str
    model_prefix:str


PROVIDERS={
    'deepseek':Provider('DeepSeek','https://api.deepseek.com',('deepseek-flash',),'DEEPSEEK_API_KEY','DeepSeekAPIKey','deepseek-'),
    'openai':Provider('OpenAI · GPT','https://api.openai.com/v1',('gpt-4.1-mini',),'OPENAI_API_KEY','OpenAIAPIKey','gpt-'),
    'claude':Provider('Anthropic · Claude','https://api.anthropic.com/v1',('claude-haiku-5-5','claude-sonnet-5-5'),
                      'ANTHROPIC_API_KEY','ClaudeAPIKey','claude-'),
    'gemini':Provider('Google · Gemini','https://generativelanguage.googleapis.com/v1beta',
                      ('gemini-3.5-flash-lite','gemini-3.8-flash'),'GEMINI_API_KEY','GeminiAPIKey','gemini-'),
}


def provider_info(provider:str) -> Provider:
    if not isinstance(provider,str) or provider not in PROVIDERS:raise ValueError('unsupported translation provider')
    return PROVIDERS[provider]


def validate_model(provider:str,model:str) -> str:
    info=provider_info(provider)
    if (not isinstance(model,str) or not model.startswith(info.model_prefix) or len(model)<=len(info.model_prefix)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{1,127}',model)):
        raise ValueError('invalid model ID for the selected translation provider')
    return model
