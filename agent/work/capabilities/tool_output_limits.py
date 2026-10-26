from pydantic_ai_harness.tool_output_limits import Band, Spill, ToolOutputLimits

from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.utils.media_store import get_overflow_store


async def build_tool_output_limits_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    过大的工具输出外溢到对象存储，失败时保留原文

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.user_id is None:
        return CapabilityResult(capability=None)
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    if not function_tools_allowed(
        adapter=ctx.adapter, supports_tools=ctx.supports_tools, has_builtin_tools=ctx.has_builtin_tools
    ):
        return CapabilityResult(capability=None)
    overflow_store = await get_overflow_store(user_id=ctx.user_id)
    if overflow_store is None:
        return CapabilityResult(capability=None)
    return CapabilityResult(
        capability=ToolOutputLimits(bands=[Band(over=10_000, action=Spill())], store=overflow_store),
        introduces_function_tool_source=True,
    )
