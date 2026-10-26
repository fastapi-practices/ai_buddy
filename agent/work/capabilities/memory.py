from pydantic_ai.capabilities import Capability
from pydantic_ai_harness import Memory

from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.agent.work.memory_store import database_memory_store
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam
from backend.plugin.ai_buddy.utils.memory_paths import memory_instructions


def build_memory_capability(ctx: CapabilityContext) -> list[CapabilityResult]:
    """
    构建当前用户的跨会话记忆能力

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.user_id is None:
        return []
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return []
    if isinstance(ctx.forwarded_props, AIBuddyChatForwardedPropsParam) and ctx.forwarded_props.memory_enabled is False:
        return []
    if not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        return []
    results = [
        CapabilityResult(
            capability=Memory(
                store=database_memory_store,
                namespace=str(ctx.user_id),
                agent_name='fba-chat',
            ),
            introduces_function_tool_source=True,
        ),
        CapabilityResult(
            capability=Capability(
                id='memory-paths',
                description='记忆路径约定',
                instructions=memory_instructions(project_id=None),
            )
        ),
    ]
    return results
