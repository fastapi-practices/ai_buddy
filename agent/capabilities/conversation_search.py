from pydantic_ai_harness.conversation_search import ConversationSearch

from backend.plugin.ai_buddy.agent.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.agent.conversation_history import BuddyConversationHistorySource
from backend.plugin.ai_buddy.agent.durability.config import step_persistence_enabled
from backend.plugin.ai_buddy.agent.step_store import ai_buddy_step_store
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType


def build_conversation_search_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    让模型检索本对话已持久化的历史，包括被压缩丢弃的早期轮次

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    if not ctx.conversation_id:
        return CapabilityResult(capability=None)
    if not step_persistence_enabled(ctx.forwarded_props):
        return CapabilityResult(capability=None)
    if not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        return CapabilityResult(capability=None)
    return CapabilityResult(
        capability=ConversationSearch(
            BuddyConversationHistorySource(ai_buddy_step_store, conversation_id=ctx.conversation_id),
            scope='conversation',
        ),
        introduces_function_tool_source=True,
    )
