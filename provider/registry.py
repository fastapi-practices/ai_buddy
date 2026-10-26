from importlib import import_module
from typing import cast

from backend.common.exception import errors
from backend.plugin.ai_buddy.enums import AIBuddyProviderType
from backend.plugin.ai_buddy.provider.base import ProviderAdapter

_ADAPTER_PATHS: dict[AIBuddyProviderType, tuple[str, str]] = {
    AIBuddyProviderType.openai: ('backend.plugin.ai_buddy.provider.openai', 'OpenAIAdapter'),
    AIBuddyProviderType.openai_responses: (
        'backend.plugin.ai_buddy.provider.openai_responses',
        'OpenAIResponsesAdapter',
    ),
    AIBuddyProviderType.openrouter: ('backend.plugin.ai_buddy.provider.openrouter', 'OpenRouterAdapter'),
    AIBuddyProviderType.anthropic: ('backend.plugin.ai_buddy.provider.anthropic', 'AnthropicAdapter'),
    AIBuddyProviderType.google: ('backend.plugin.ai_buddy.provider.google', 'GoogleAdapter'),
    AIBuddyProviderType.xai: ('backend.plugin.ai_buddy.provider.xai', 'XaiAdapter'),
}
_ADAPTERS: dict[AIBuddyProviderType, ProviderAdapter] = {}


def get_provider_adapter(provider_type: int | AIBuddyProviderType) -> ProviderAdapter:
    """
    获取供应商适配器

    :param provider_type: 供应商类型
    :return:
    """
    try:
        resolved_type = AIBuddyProviderType(provider_type)
    except (TypeError, ValueError) as exc:
        raise errors.NotFoundError(msg=f'当前不支持此供应商: {provider_type}') from exc
    adapter = _ADAPTERS.get(resolved_type)
    if adapter is not None:
        return adapter
    adapter_path = _ADAPTER_PATHS.get(resolved_type)
    if adapter_path is None:
        raise errors.NotFoundError(msg=f'当前不支持此供应商: {provider_type}')
    module_name, class_name = adapter_path
    adapter_cls = cast('type[ProviderAdapter]', getattr(import_module(module_name), class_name))
    adapter = adapter_cls()
    _ADAPTERS[resolved_type] = adapter
    return adapter
