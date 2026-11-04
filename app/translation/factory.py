from .client import DeepSeekClient
from .official_client import OfficialAPIClient


def create_client(config,credential,**kwargs):
    config.validate()
    if credential.provider!=config.provider:raise ValueError('credential does not belong to selected provider')
    return (DeepSeekClient if config.provider=='deepseek' else OfficialAPIClient)(config,credential,**kwargs)
