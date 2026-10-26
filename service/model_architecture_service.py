from time import perf_counter
from typing import Any

import httpx

from starlette.concurrency import run_in_threadpool

from backend.common.exception import errors
from backend.common.log import log
from backend.plugin.ai_buddy.enums import (
    AIBuddyChatThinkingType,
    AIBuddyModelKind,
    AIBuddyModelModality,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.schema.model import AIBuddyThinkingPolicy
from backend.plugin.ai_buddy.schema.model_architecture import GetAIBuddyModelArchitectureSuggestion
from backend.plugin.ai_buddy.utils.model_catalog import validate_model_binding

_PROVIDER_IDS = {
    AIBuddyProviderType.openai: 'openai',
    AIBuddyProviderType.anthropic: 'anthropic',
    AIBuddyProviderType.google: 'google',
    AIBuddyProviderType.xai: 'xai',
    AIBuddyProviderType.openrouter: 'openrouter',
    AIBuddyProviderType.openai_responses: 'openai',
}


class AIBuddyModelArchitectureService:
    """模型目录与架构建议服务类"""

    @staticmethod
    async def fetch_catalog() -> dict[str, Any]:
        """同步 models.dev 最新完整模型目录"""
        started = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get('https://models.dev/api.json?type=all')
                response.raise_for_status()
                downloaded = perf_counter()
                payload = await run_in_threadpool(response.json)
        except (httpx.HTTPError, ValueError) as exc:
            raise errors.RequestError(msg='获取 models.dev 模型数据失败，请稍后重试') from exc
        if not isinstance(payload, dict):
            raise errors.RequestError(msg='获取 models.dev 模型数据失败，请稍后重试')
        log.info(
            f'models.dev 目录获取耗时: download={(downloaded - started) * 1000:.2f}ms '
            f'parse={(perf_counter() - downloaded) * 1000:.2f}ms bytes={len(response.content)}'
        )
        return payload

    @staticmethod
    def _build_suggestion(  # ruff: ignore[complex-structure]
        *, data: dict[str, Any], provider_type: AIBuddyProviderType, current_kind: AIBuddyModelKind
    ) -> GetAIBuddyModelArchitectureSuggestion:
        """
        将模型目录条目转换为当前供应商支持的架构建议

        :param data: 模型目录条目
        :param provider_type: 供应商类型
        :param current_kind: 当前模型类型
        :return:
        """
        modalities = data.get('modalities')
        output = modalities.get('output') if isinstance(modalities, dict) else None
        image_output = isinstance(output, list) and 'image' in output
        kind = None
        if image_output:
            try:
                validate_model_binding(kind=AIBuddyModelKind.image, provider_type=provider_type)
            except errors.RequestError:
                pass
            else:
                kind = AIBuddyModelKind.image

        kind_supported = not image_output or kind is not None
        effective_kind = kind or current_kind
        raw_inputs = modalities.get('input') if isinstance(modalities, dict) else None
        input_modalities = None
        if kind_supported and isinstance(raw_inputs, list) and 'text' in raw_inputs:
            allowed = {
                AIBuddyModelKind.chat: frozenset(AIBuddyModelModality),
                AIBuddyModelKind.embedding: {AIBuddyModelModality.text},
                AIBuddyModelKind.image: {AIBuddyModelModality.text, AIBuddyModelModality.image},
            }[effective_kind]
            input_modalities = [item for item in AIBuddyModelModality if item in raw_inputs and item in allowed]
        chat_supported = kind_supported and effective_kind == AIBuddyModelKind.chat
        tools = data.get('tool_call') if chat_supported else None
        thinking = data.get('reasoning') if chat_supported else None
        thinking_policy = None
        options = data.get('reasoning_options')
        if thinking is True and isinstance(options, list):
            levels: list[AIBuddyChatThinkingType] = []
            for option in options:
                if not isinstance(option, dict) or option.get('type') != 'effort':
                    continue
                values = option.get('values')
                if not isinstance(values, list):
                    continue
                for value in values:
                    if (
                        isinstance(value, str)
                        and value in AIBuddyChatThinkingType._value2member_map_
                        and value != 'off'
                    ):
                        level = AIBuddyChatThinkingType(value)
                        if level not in levels:
                            levels.append(level)
            can_disable = any(isinstance(option, dict) and option.get('type') == 'toggle' for option in options)
            if levels or can_disable:
                thinking_policy = AIBuddyThinkingPolicy(levels=levels, can_disable=can_disable)
        limit = data.get('limit')
        limit = limit if isinstance(limit, dict) else {}
        context_window = limit.get('context')
        max_output_tokens = limit.get('output')

        return GetAIBuddyModelArchitectureSuggestion(
            source='models.dev',
            last_updated=data.get('last_updated') if isinstance(data.get('last_updated'), str) else None,
            kind=kind,
            input_modalities=input_modalities,
            tools=tools if isinstance(tools, bool) else None,
            thinking=thinking if isinstance(thinking, bool) else None,
            thinking_policy=thinking_policy,
            context_window=context_window if type(context_window) is int and context_window > 0 else None,
            max_output_tokens=max_output_tokens if type(max_output_tokens) is int and max_output_tokens > 0 else None,
        )

    def get_suggestion(
        self,
        *,
        catalog: dict[str, Any],
        provider_type: AIBuddyProviderType,
        model_id: str,
        current_kind: AIBuddyModelKind,
    ) -> GetAIBuddyModelArchitectureSuggestion:
        """
        从完整模型目录获取指定模型的架构建议

        :param catalog: 完整模型目录
        :param provider_type: 供应商类型
        :param model_id: 模型标识
        :param current_kind: 当前模型类型
        :return:
        """
        for source in dict.fromkeys((_PROVIDER_IDS[provider_type], 'openrouter', 'opencode-go', 'opencode')):
            provider = catalog.get(source)
            models = provider.get('models') if isinstance(provider, dict) else None
            data = models.get(model_id) if isinstance(models, dict) else None
            if isinstance(data, dict) and data.get('id') == model_id:
                return self._build_suggestion(data=data, provider_type=provider_type, current_kind=current_kind)
        raise errors.NotFoundError(msg='models.dev 尚未收录该模型')


ai_buddy_model_architecture_service: AIBuddyModelArchitectureService = AIBuddyModelArchitectureService()
