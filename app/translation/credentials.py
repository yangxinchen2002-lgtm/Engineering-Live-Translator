"""Read an environment secret or a named Windows user credential; never log values."""
from __future__ import annotations
from app.i18n import tr as _tr
from dataclasses import dataclass, field
import getpass
import os
import sys
from app.profile import profile_id
from .providers import provider_info

TARGET = 'ELT/DeepSeekAPIKey'


def credential_target(provider:str='deepseek') -> str:
    name=provider_info(provider).credential_name
    profile=profile_id()
    return f'ELT/{profile}/{name}' if profile else f'ELT/{name}'


class CredentialStoreError(RuntimeError):
    """Only operation and numeric Windows status may leave the storage boundary."""
    def __init__(self, operation: str, winerror: int | None = None):
        self.operation = operation
        self.winerror = winerror if type(winerror) is int else None
        code = f'; Windows error {self.winerror}' if self.winerror is not None else ''
        super().__init__(f'Windows credential {operation} failed{code}; secret omitted')


def credential_error_message(error: Exception) -> str:
    """Safe GUI text: never format an underlying exception containing a secret."""
    if isinstance(error, CredentialStoreError):
        code = error.winerror
        suffix = f"{_tr('（错误码 ')}{code}）" if code is not None else ''
        if error.operation == 'verify':
            return f"{_tr('密钥已写入 Windows，但读取验证失败')}{suffix}{_tr('。请重新打开 ELT 后重试；如设置过该服务的密钥环境变量，请检查其内容。')}"
        if code == 5:
            return f"{_tr('Windows 拒绝访问凭据库')}{suffix}{_tr('。请从当前用户的正常桌面打开 ELT 后重试。')}"
        if code == 1312:
            return f"{_tr('当前 Windows 登录会话无法使用凭据库')}{suffix}{_tr('。请从正常桌面重新打开 ELT。')}"
        return f"{_tr('Windows 凭据')}{(_tr('读取') if error.operation == 'read' else _tr('保存'))}{_tr('失败')}{suffix}{_tr('。密钥未写入日志。')}"
    if isinstance(error, ValueError):
        return _tr('密钥格式不正确：请只粘贴 API Key，不要包含引号、空格或换行，长度应为 8–512 个字符。')
    return _tr('密钥处理组件发生错误，请重新打开 ELT 后重试。密钥未写入日志。')


@dataclass(frozen=True)
class Credential:
    value: str = field(repr=False)
    source: str = 'unavailable'
    provider: str = 'deepseek'


def validate_key(value: str) -> str:
    value = value.strip()
    if not 8 <= len(value) <= 512 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('invalid API key format; key value omitted')
    return value


def read_credential(provider:str='deepseek') -> Credential | None:
    info=provider_info(provider)
    value = os.environ.get(info.environment) if profile_id() is None else None
    if value:
        return Credential(validate_key(value), 'environment',provider)
    if os.name == 'nt':
        import win32cred
        try:
            data = win32cred.CredRead(credential_target(provider), win32cred.CRED_TYPE_GENERIC)
        except Exception as exc:
            if getattr(exc, 'winerror', None) == 1168:
                return None
            raise CredentialStoreError('read', getattr(exc, 'winerror', None)) from None
        raw = data['CredentialBlob']
        try:value = raw.decode('utf-16-le') if isinstance(raw, bytes) else raw
        except UnicodeError:raise RuntimeError('stored credential encoding is invalid; secret omitted') from None
        return Credential(validate_key(value), 'windows_credential',provider)
    return None


def manage_credential(action: str,provider:str='deepseek') -> dict:
    info=provider_info(provider)
    if action == 'status':
        key = read_credential() if provider=='deepseek' else read_credential(provider)
        return {'available': key is not None, 'source': key.source if key else 'unavailable', 'target': credential_target(provider)}
    if os.name != 'nt':
        raise RuntimeError('credential storage requires Windows; use a session environment variable')
    import win32cred
    if action == 'set':
        if not sys.stdin.isatty():
            raise RuntimeError('run api-key set in your local interactive terminal; never pass the key as an argument')
        value = validate_key(getpass.getpass(info.label+' API key (hidden): '))
        return store_credential(value,provider)
    if action == 'delete':
        try:
            win32cred.CredDelete(credential_target(provider), win32cred.CRED_TYPE_GENERIC, 0)
        except Exception as exc:
            if getattr(exc, 'winerror', None) != 1168:
                raise RuntimeError('credential deletion failed; secret omitted') from None
        return {'deleted': True, 'target': credential_target(provider)}
    raise ValueError('unknown credential action')


def store_credential(value:str,provider:str='deepseek') -> dict:
    """Shared by the hidden terminal input and GUI; never accepts command-line secrets."""
    value=validate_key(value)
    target=credential_target(provider)
    if os.name!='nt':raise RuntimeError('credential storage requires Windows')
    import win32cred
    try:
        win32cred.CredWrite({'Type':win32cred.CRED_TYPE_GENERIC,'TargetName':target,'UserName':'ELT',
                            # pywin32 312 accepts Unicode here and encodes it itself.
                            # CredRead, in contrast, returns UTF-16-LE bytes.
                            'CredentialBlob':value,'Persist':win32cred.CRED_PERSIST_LOCAL_MACHINE},0)
    except Exception as error:
        raise CredentialStoreError('write', getattr(error, 'winerror', None)) from None
    return {'stored':True,'target':target,'value_logged':False}
