from pydantic_ai_harness.planning import Planning

from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.utils.plan_store import get_plan_store


def build_planning_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    构建任务规划能力

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    if not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        return CapabilityResult(capability=None)
    store = None
    if ctx.user_id is not None and ctx.conversation_id:
        store = get_plan_store(user_id=ctx.user_id, conversation_id=ctx.conversation_id)
    return CapabilityResult(
        capability=Planning(
            store=store,
            enable_subtasks=True,
            guidance='复杂工作先拆成可执行步骤，完成一项再更新状态',
        ),
        introduces_function_tool_source=True,
    )
