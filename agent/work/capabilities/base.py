from collections.abc import Awaitable, Callable, Sequence

from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyProviderType
from backend.plugin.ai_buddy.provider.base import ProviderAdapter

type CapabilityOutcome = CapabilityResult | Sequence[CapabilityResult]
type CapabilityBuilder = Callable[[CapabilityContext], CapabilityOutcome | Awaitable[CapabilityOutcome]]


def function_tools_allowed(
    *,
    adapter: ProviderAdapter,
    supports_tools: bool,
    has_builtin_tools: bool,
) -> bool:
    """
    判断当前组合是否允许函数工具

    Google 不支持 builtin tools 与 function tools 混用

    :param adapter: 供应商适配器
    :param supports_tools: 模型是否支持 function tools
    :param has_builtin_tools: 是否已存在 builtin tools
    :return:
    """
    if not supports_tools:
        return False
    return not (adapter.provider_type == AIBuddyProviderType.google and has_builtin_tools)


def native_builtin_allowed(*, adapter: ProviderAdapter) -> bool:
    """
    判断当前供应商是否允许挂载原生 builtin 工具

    Google 不能把原生工具和工作区函数工具混用，work agent 优先保留函数工具

    :param adapter: 供应商适配器
    :return:
    """
    return adapter.provider_type != AIBuddyProviderType.google
