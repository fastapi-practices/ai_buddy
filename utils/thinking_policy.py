from backend.common.exception import errors
from backend.plugin.ai_buddy.enums import AIBuddyChatThinkingType, AIBuddyModelCapability
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam
from backend.plugin.ai_buddy.schema.model import AIBuddyThinkingPolicy

_THINKING_OVERRIDE_KEYS = frozenset({
    'thinking',
    'openai_reasoning_effort',
    'anthropic_thinking',
    'google_thinking_config',
    'openrouter_reasoning',
    'xai_reasoning_effort',
})


def resolve_thinking_policy(
    *,
    forwarded_props: AIBuddyChatForwardedPropsParam,
    capabilities: frozenset[AIBuddyModelCapability],
    policy: dict | None,
) -> AIBuddyChatForwardedPropsParam:
    """
    按模型级策略校验本轮思考强度，并应用未指定时的默认档位

    :param forwarded_props: 转发参数
    :param capabilities: 模型能力集合
    :param policy: 策略配置
    :return:
    """
    requested = forwarded_props.thinking
    overrides = {
        key
        for key in forwarded_props.extra_body or {}
        if key in _THINKING_OVERRIDE_KEYS or key.startswith('openai_reasoning_')
    }
    if overrides:
        raise errors.RequestError(msg='请使用 thinking 参数而非 extra_body 修改思考强度')
    if requested is not None and AIBuddyModelCapability.thinking not in capabilities:
        raise errors.RequestError(msg='当前模型未启用思考能力')
    if policy is None:
        if requested is not None:
            raise errors.RequestError(msg='当前模型未配置可选的思考档位')
        return forwarded_props

    config = AIBuddyThinkingPolicy.model_validate(policy)
    if requested == AIBuddyChatThinkingType.off:
        if not config.can_disable:
            raise errors.RequestError(msg='当前模型不支持关闭思考')
    elif requested is not None and requested not in config.levels:
        raise errors.RequestError(msg='当前模型不支持所选思考强度')
    elif requested is None and config.default_level is not None:
        return forwarded_props.model_copy(update={'thinking': config.default_level})
    return forwarded_props
