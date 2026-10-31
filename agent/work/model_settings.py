from typing import cast

from pydantic_ai import ModelSettings

from backend.plugin.ai_buddy.provider.base import COMMON_MODEL_SETTING_FIELDS, ProviderAdapter
from backend.plugin.ai_buddy.schema.chat import AIBuddyForwardedPropsParam
from backend.plugin.ai_buddy.utils.thinking_policy import EXTRA_BODY_BLOCKED_KEYS, is_thinking_override_key


def build_model_settings(
    *,
    adapter: ProviderAdapter,
    forwarded_props: AIBuddyForwardedPropsParam,
    model_name: str | None = None,
    max_output_tokens: int | None = None,
) -> ModelSettings:
    """
    按供应商构建模型配置

    :param adapter: 供应商适配器
    :param forwarded_props: 聊天扩展参数
    :param model_name: 模型名称
    :param max_output_tokens: 模型最大输出 token 上限
    :return:
    """
    included = COMMON_MODEL_SETTING_FIELDS - adapter.capabilities['excluded_setting_fields']
    payload = forwarded_props.model_dump(include=included, exclude_unset=True, exclude_none=True)
    if 'parallel_tool_calls' in included:
        payload['parallel_tool_calls'] = True
    extra = getattr(forwarded_props, 'extra_body', None) or {}
    known_keys = adapter.settings_cls.__annotations__.keys() - EXTRA_BODY_BLOCKED_KEYS
    payload.update({
        key: value for key, value in extra.items() if key in known_keys and not is_thinking_override_key(key)
    })
    payload.update(
        adapter.resolve_extra_settings(
            forwarded_props=forwarded_props,
            model_name=model_name,
        )
    )
    if max_output_tokens is not None and 'max_tokens' in included:
        current = payload.get('max_tokens')
        if current is not None and current > max_output_tokens:
            payload['max_tokens'] = max_output_tokens
    return cast('ModelSettings', adapter.settings_cls(**payload))
