from typing import Any

import httpx

from pydantic import ValidationError

from backend.common.exception import errors
from backend.common.log import log
from backend.plugin.ai_buddy.enums import AIBuddyProviderType
from backend.plugin.ai_buddy.provider.base import ProviderModelSnapshot, normalize_provider_api_host


def _parse_provider_model(data: dict[str, Any]) -> ProviderModelSnapshot:
    """
    解析供应商模型标识与展示信息

    :param data: 供应商返回的模型条目
    :return:
    """
    model_id = data.get('id')
    if not isinstance(model_id, str) or not model_id.strip():
        raise ValueError('模型 ID 缺失')
    object_name = data.get('object')
    display_name = data.get('name') if isinstance(data.get('name'), str) else data.get('display_name')
    created = data.get('created')
    created_at = None if isinstance(created, bool) or not isinstance(created, (int, float)) else int(created)
    return ProviderModelSnapshot(
        id=model_id,
        object=object_name if isinstance(object_name, str) else None,
        created=created_at,
        display_name=display_name if isinstance(display_name, str) else None,
    )


async def _fetch_provider_models_payload(*, url: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    """
    请求供应商模型列表

    :param url: 模型列表地址
    :param headers: 请求头
    :return:
    """
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as e:
            log.error(f'获取供应商模型列表失败：{e}')
            raise errors.RequestError(msg='获取供应商模型列表失败，请稍后重试') from e
        except ValueError as e:
            log.error(f'供应商模型列表 JSON 解析失败：{e}')
            raise errors.RequestError(msg='供应商返回的模型数据不是合法 JSON') from e

    items = payload.get('data') if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise errors.RequestError(msg='供应商返回的模型数据格式不正确')
    return [item for item in items if isinstance(item, dict)]


async def list_openai_compat_models(
    *,
    provider_type: AIBuddyProviderType,
    api_key: str,
    api_host: str,
) -> list[ProviderModelSnapshot]:
    """
    获取 OpenAI 兼容供应商模型列表

    :param provider_type: 供应商类型
    :param api_key: 接口密钥
    :param api_host: 接口地址
    :return:
    """
    url = f'{normalize_provider_api_host(provider_type, api_host)}/models'
    items = await _fetch_provider_models_payload(url=url, headers={'Authorization': f'Bearer {api_key}'})
    try:
        return [_parse_provider_model(item) for item in items]
    except (KeyError, TypeError, ValueError, ValidationError) as e:
        log.error(f'供应商模型列表数据格式错误：{e}')
        raise errors.RequestError(msg='供应商返回的模型数据格式不正确') from e
