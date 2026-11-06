from collections.abc import Sequence

from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition
from pydantic_ai_harness import CodeMode

from backend.plugin.ai_buddy.agent.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.agent.capabilities.runtime_hooks import resolve_work_tool_policy
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType, AIBuddyToolPolicy
from backend.plugin.ai_buddy.security.jev import is_jev_tool_risk, jev_enabled
from backend.plugin.ai_buddy.security.tool_policy import is_mcp_tool

_CODE_MODE_TOOLS: tuple[str, ...] = (
    'search_knowledge',
    'get_knowledge',
    'read_skill_file',
    'list_artifacts',
    'get_artifact',
    'write_artifact',
    'get_current_time',
    'search_conversation_history',
)


def build_sandbox_capabilities(ctx: CapabilityContext) -> Sequence[CapabilityResult]:
    """
    构建本地工作沙箱，不使用模型供应商托管沙箱

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return ()
    if not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        return ()
    policies = dict(ctx.forwarded_props.tool_policies or {})
    mcp_approve_writes = ctx.forwarded_props.mcp_approve_writes
    has_jev = jev_enabled()

    def sandbox_tool(run_ctx: RunContext[ChatAgentDeps], tool_def: ToolDefinition) -> bool:
        """
        判断工具是否属于当前沙箱能力

        :param run_ctx: 运行上下文
        :param tool_def: 工具定义
        :return:
        """
        del run_ctx
        if tool_def.name not in _CODE_MODE_TOOLS or tool_def.kind != 'function':
            return False
        policy = resolve_work_tool_policy(tool_def=tool_def, policies=policies, mcp_approve_writes=mcp_approve_writes)
        if policy != AIBuddyToolPolicy.allow:
            return False
        return not (has_jev and (is_jev_tool_risk(tool_def.name) or is_mcp_tool(tool_def)))

    return (
        CapabilityResult(
            capability=CodeMode(
                tools=sandbox_tool,
                eager=False,
                speculate='declared',
            ),
            introduces_function_tool_source=True,
        ),
    )
