"""One explicit course-notes request; credentials are read only inside this process."""
from app.i18n import tr as _tr
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys


def emit(event,**fields):print(json.dumps({'event':event,**fields},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args()
    from app.ui.lifetime import JOB_ENV,join_owner_job
    if os.environ.get(JOB_ENV):join_owner_job(os.environ[JOB_ENV])
    try:
        raw=sys.stdin.buffer.read(40*1024*1024+1)
        if len(raw)>40*1024*1024:raise ValueError(_tr('课程材料超过处理上限。'))
        payload=json.loads(raw.decode('utf-8'))
        from .config import request_config
        config=request_config(payload)
        from app.translation.credentials import read_credential
        credential=read_credential(config.provider)
        if credential is None:raise ValueError(_tr('请先为 AI 总结所选服务配置密钥。'))
        from .service import create_notes
        asyncio.run(create_notes(payload,args.directory,credential,emit))
        return 0
    except Exception as error:
        from app.translation.client import ProviderError
        messages={'authentication_failed':_tr('AI 总结服务密钥验证失败，请检查所选服务的密钥。'),
                  'insufficient_balance':_tr('AI 总结服务余额不足，请检查所选服务的账户。'),
                  'invalid_request_or_model':_tr('AI 总结模型不可用，请检查模型名称与访问权限。'),
                  'rate_limited':_tr('AI 总结服务请求过于频繁，请稍后重试。'),
                  'network_timeout':_tr('AI 整理连接超时，可稍后手动重试。'),
                  'network_error':_tr('AI 整理网络不可用，可稍后手动重试。'),
                  'translation_finish_length':_tr('AI 整理返回内容过长，未保存不完整 AI 稿，可重试较短课程。')}
        message=messages.get(error.code,_tr('AI 整理服务暂时不可用，请稍后重试。')) if isinstance(error,ProviderError) else str(error)[:300]
        emit('notes_error',message=message);return 2


if __name__=='__main__':raise SystemExit(main())
