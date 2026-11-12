from __future__ import annotations

from typing import TYPE_CHECKING

from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.provider.registry import get_provider_adapter
from backend.plugin.ai_buddy.service.model_service import ai_buddy_model_service

if TYPE_CHECKING:
    import httpx2

    from pydantic_ai.models import Model


def parse_fallback_bindings(value: str) -> list[tuple[int, str]]:
    """
    解析备用模型绑定列表，格式为供应商 ID 与模型 ID 的冒号组合

    :param value: 配置原文
    :return:
    """
    bindings: list[tuple[int, str]] = []
    for item in value.split(','):
        binding = item.strip()
        if not binding:
            continue
        provider_id, _, model_id = binding.partition(':')
        if not provider_id.strip().isdigit() or not model_id.strip():
            log.warning(f'备用模型绑定格式无效: {binding}')
            continue
        bindings.append((int(provider_id), model_id.strip()))
    return bindings


async def build_fallback_models(*, user_id: int | None, http_client: httpx2.AsyncClient) -> list[Model]:
    """
    按配置构建备用模型链，单个绑定不可用时跳过而不影响本轮

    :param user_id: 用户 ID，内部调用可为空
    :param http_client: 共享 HTTP 客户端
    :return:
    """
    bindings = parse_fallback_bindings(settings.AI_BUDDY_AGENT_FALLBACK_MODELS)
    if not bindings:
        return []
    models: list[Model] = []
    async with async_db_session() as db:
        for provider_id, model_id in bindings:
            try:
                provider, model = await ai_buddy_model_service.get_enabled_binding(
                    db=db, provider_id=provider_id, model_id=model_id, user_id=user_id
                )
                adapter = get_provider_adapter(provider.type)
                models.append(
                    adapter.create_model(
                        model_name=model.model_id,
                        api_key=provider.api_key,
                        base_url=provider.api_host,
                        http_client=http_client,
                    )
                )
            except (errors.BaseExceptionError, ValueError) as exc:
                log.warning(f'备用模型不可用 provider_id={provider_id} model_id={model_id}: {exc}')
    return models
