from dataclasses import replace

from pydantic_ai import ApprovalRequired, ModelRetry, RunContext
from pydantic_ai.capabilities import PrepareTools
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from backend.common.log import log
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType, AIBuddyToolPolicy
from backend.plugin.ai_buddy.security.tool_policy import is_mcp_tool, resolve_tool_policy
from backend.plugin.ai_buddy.service.approval_audit_service import ai_buddy_approval_audit_service


def resolve_work_tool_policy(
    *,
    tool_def: ToolDefinition,
    policies: dict[str, str],
    mcp_approve_writes: bool,
) -> AIBuddyToolPolicy:
    """
    按工具来源和本轮覆盖解析工作工具策略

    :param tool_def: 工具定义
    :param policies: 本轮工具策略
    :param mcp_approve_writes: MCP 默认询问
    :return:
    """
    default = AIBuddyToolPolicy.ask if mcp_approve_writes and is_mcp_tool(tool_def) else AIBuddyToolPolicy.allow
    return resolve_tool_policy(tool_name=tool_def.name, policies=policies, default=default)


def build_tool_policy_hooks(
    *,
    policies: dict[str, str],
    mcp_approve_writes: bool,
    allow_ask: bool = True,
) -> Hooks[ChatAgentDeps]:
    """
    构建主代理和子代理共用的工具执行策略

    :param policies: 本轮工具策略
    :param mcp_approve_writes: MCP 默认询问
    :param allow_ask: 是否支持挂起后恢复，子代理不支持时拒绝 ask
    :return:
    """
    policies = dict(policies)
    hooks = Hooks(id='work-runtime-hooks')

    @hooks.on.before_tool_execute
    async def log_and_approve_tool(
        run_ctx: RunContext[ChatAgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: object,
    ) -> object:
        """记录工具启动并应用审批策略

        :param run_ctx: 运行上下文
        :param call: 工具调用
        :param tool_def: 工具定义
        :param args: 工具参数
        :return:
        """
        log.info(f'ai-buddy 工具开始: {call.tool_name}')
        policy = resolve_work_tool_policy(tool_def=tool_def, policies=policies, mcp_approve_writes=mcp_approve_writes)
        if policy == AIBuddyToolPolicy.deny:
            raise ModelRetry(f'工具已被拒绝: {call.tool_name}')
        if policy == AIBuddyToolPolicy.ask:
            if not allow_ask:
                raise ModelRetry(f'工具需要人工确认，请交由主代理调用: {call.tool_name}')
            if run_ctx.deps.user_id is None or not run_ctx.deps.conversation_id or not run_ctx.run_id:
                raise ModelRetry('审批工具缺少用户、对话或运行身份')
            await ai_buddy_approval_audit_service.request_work(
                user_id=run_ctx.deps.user_id,
                conversation_id=run_ctx.deps.conversation_id,
                run_id=run_ctx.run_id,
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                arguments=call.args_as_dict(),
                approved=run_ctx.tool_call_approved,
            )
            if not run_ctx.tool_call_approved:
                raise ApprovalRequired(metadata={'reason': f'需要确认: {call.tool_name}', 'origin': 'tool_policy'})
        return args

    @hooks.on.after_tool_execute
    def log_tool_done(
        run_ctx: RunContext[ChatAgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: object,
        result: object,
    ) -> object:
        """记录工具执行结束事件

        :param run_ctx: 运行上下文
        :param call: 工具调用
        :param tool_def: 工具定义
        :param args: 工具参数
        :param result: 执行结果
        :return:
        """
        del run_ctx, tool_def, args
        log.info(f'ai-buddy 工具完成: {call.tool_name}')
        return result

    return hooks


async def build_runtime_hooks_capability(ctx: CapabilityContext) -> list[CapabilityResult]:  # ruff: ignore[unused-async]
    """
    构建观测、MCP 延迟加载与显式工具策略审批

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return []

    hooks = build_tool_policy_hooks(
        policies=ctx.forwarded_props.tool_policies or {},
        mcp_approve_writes=ctx.forwarded_props.mcp_approve_writes,
    )

    def defer_mcp_tools(
        run_ctx: RunContext[ChatAgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """按策略标记需要审批的 MCP 工具

        :param run_ctx: 运行上下文
        :param tool_defs: 工具定义列表
        :return:
        """
        del run_ctx
        return [replace(tool_def, defer_loading=True) if is_mcp_tool(tool_def) else tool_def for tool_def in tool_defs]

    return [CapabilityResult(capability=hooks), CapabilityResult(capability=PrepareTools(defer_mcp_tools))]
