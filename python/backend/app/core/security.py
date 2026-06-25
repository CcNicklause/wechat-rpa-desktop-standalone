import re
from typing import Any

from fastapi import Depends, Header, Request, status

from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import AppError

PHONE_PATTERN = re.compile(r'^[0-9A-Za-z_+\-]{5,32}$')
BATCH_KEYS = {'phones', 'phone_list', 'targets', 'contacts', 'items', 'batch'}


def mask_phone(value: str | None) -> str | None:
    if not value:
        return value
    text = str(value)
    if len(text) <= 7:
        return text[0:2] + '***' + text[-1:]
    return text[:3] + '****' + text[-4:]


def validate_phone(value: str) -> str:
    target = value.strip()
    if not PHONE_PATTERN.match(target):
        raise AppError('INVALID_PHONE', '手机号/微信号格式不符合本地 Demo 校验规则')
    return target


def reject_batch_payload(payload: Any) -> None:
    if isinstance(payload, dict):
        lowered = {str(key).lower() for key in payload.keys()}
        if lowered & BATCH_KEYS:
            raise AppError('BATCH_NOT_ALLOWED', '本 Demo 仅允许单个客户的一对一跟进，禁止批量请求')
        for value in payload.values():
            reject_batch_payload(value)
    elif isinstance(payload, list):
        raise AppError('BATCH_NOT_ALLOWED', '本 Demo 禁止列表/批量目标请求')


def require_local_request(request: Request) -> None:
    client = request.client.host if request.client else 'unknown'
    if client not in {'127.0.0.1', '::1', 'localhost', 'testclient'}:
        raise AppError('LOCAL_ONLY', '本地 Demo 仅允许 localhost 访问', status.HTTP_403_FORBIDDEN)


def require_auth(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    require_local_request(request)
    expected = f'Bearer {settings.api_token}'
    if authorization != expected:
        raise AppError('UNAUTHORIZED', '缺少或错误的本地 API Token', status.HTTP_401_UNAUTHORIZED)
