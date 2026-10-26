from pydantic_ai.capabilities import Toolset
from pydantic_ai.toolsets import FunctionToolset

from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.utils.timezone import timezone


def get_current_time() -> str:
    """获取当前时间"""
    return timezone.to_str(timezone.now())


def build_builtin_toolset_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    构建项目内置 toolset 能力

    :param ctx: 能力构建上下文
    :return:
    """
    if not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        return CapabilityResult(capability=None)
    return CapabilityResult(
        capability=Toolset(FunctionToolset[ChatAgentDeps]([get_current_time])),
        introduces_function_tool_source=True,
    )
