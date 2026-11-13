from collections.abc import Sequence
from inspect import isawaitable

from backend.plugin.ai_buddy.agent.capabilities.base import CapabilityBuilder
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult

_extension_builders: list[CapabilityBuilder] = []


def register_ai_buddy_capability_builder(builder: CapabilityBuilder) -> None:
    """
    注册依赖插件提供的能力构建器

    :param builder: 能力构建器
    :return:
    """
    if builder not in _extension_builders:
        _extension_builders.append(builder)


async def build_extension_capabilities(context: CapabilityContext) -> list[CapabilityResult]:
    """
    构建依赖插件注册的扩展能力

    :param context: 能力构建上下文
    :return:
    """
    results: list[CapabilityResult] = []
    for builder in tuple(_extension_builders):
        outcomes = builder(context)
        if isawaitable(outcomes):
            outcomes = await outcomes
        normalized: Sequence[CapabilityResult] = outcomes if isinstance(outcomes, Sequence) else (outcomes,)
        results.extend(normalized)
    return results
