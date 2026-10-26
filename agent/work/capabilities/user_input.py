from dataclasses import dataclass
from typing import Any

from pydantic_ai import CapabilityEvent, RunContext
from pydantic_ai.capabilities import Toolset
from pydantic_ai.toolsets import FunctionToolset

from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.agent.work.input_requests import wait_for_input
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.schema.input_request import AIBuddyInputQuestion


@dataclass(kw_only=True)
class BuddyUserInputEvent(
    CapabilityEvent,
    namespace='buddy_input',
    name='request',
):
    """公开问题和状态，禁止携带秘密答案"""

    request: dict[str, Any]


async def ask_user(ctx: RunContext[ChatAgentDeps], title: str, questions: list[AIBuddyInputQuestion]) -> dict[str, Any]:
    """向用户提出最多十个文本、单选或多选问题并等待回复；不得索取密码和密钥

    :param ctx: 运行上下文
    :param title: 标题
    :param questions: 问题列表
    :return:
    """
    if not ctx.deps.conversation_id:
        return {'cancelled': True, 'reason': '当前运行没有可交互的对话'}

    async def emit(request: dict[str, Any]) -> None:
        """发布本轮运行的界面事件

        :param request: 当前请求
        :return:
        """
        await ctx.emit(BuddyUserInputEvent(request=request))

    result = await wait_for_input(
        conversation_id=ctx.deps.conversation_id,
        title=title,
        questions=questions,
        emit=emit,
        tool_call_id=ctx.tool_call_id,
    )
    return {'cancelled': True} if result is None else {'answers': result}


def build_user_input_capability(ctx: CapabilityContext) -> CapabilityResult:
    """为有归属的工作会话开放结构化问答

    :param ctx: 运行上下文
    :return:
    """
    if (
        ctx.user_id is None
        or not ctx.conversation_id
        or ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text
        or not function_tools_allowed(
            adapter=ctx.adapter, supports_tools=ctx.supports_tools, has_builtin_tools=ctx.has_builtin_tools
        )
    ):
        return CapabilityResult(capability=None)
    toolset: FunctionToolset[ChatAgentDeps] = FunctionToolset[ChatAgentDeps]()
    toolset.tool(ask_user)
    return CapabilityResult(capability=Toolset(toolset), introduces_function_tool_source=True)
