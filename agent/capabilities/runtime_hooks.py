from dataclasses import replace

from pydantic_ai import ApprovalRequired, ModelRetry, RunContext
from pydantic_ai.capabilities import PrepareTools
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition

from backend.common.log import log
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType, AIBuddyToolPolicy
from backend.plugin.ai_buddy.security.tool_policy import (
    RESOURCE_WRITE_TOOLS,
    SANDBOX_CONFIRM_TOOLS,
    is_mcp_tool,
    resolve_tool_policy_with_dependencies,
)
from backend.plugin.ai_buddy.service.approval_audit_service import ai_buddy_approval_audit_service


def resolve_work_tool_policy(
    *,
    tool_def: ToolDefinition,
    policies: dict[str, str],
    mcp_approve_writes: bool,
) -> AIBuddyToolPolicy:
    """
    按工具来源和本轮覆盖解析工作工具策略，并继承依赖限制

    :param tool_def: 工具定义
    :param policies: 本轮工具策略
    :param mcp_approve_writes: MCP 默认询问
    :return:
    """
    needs_confirm = (
        tool_def.name in RESOURCE_WRITE_TOOLS
        or tool_def.name in SANDBOX_CONFIRM_TOOLS
        or (mcp_approve_writes and is_mcp_tool(tool_def))
    )
    default = AIBuddyToolPolicy.ask if needs_confirm else AIBuddyToolPolicy.allow
    return resolve_tool_policy_with_dependencies(tool_name=tool_def.name, policies=policies, default=default)


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
        """
        记录工具启动并应用审批策略

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
        """
        记录工具执行结束事件

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


def prepare_work_tools(
    *,
    tool_defs: list[ToolDefinition],
    policies: dict[str, str],
    mcp_approve_writes: bool,
) -> list[ToolDefinition]:
    """
    隐藏显式拒绝的工具，并延迟暴露 MCP 工具

    :param tool_defs: 本轮工具定义
    :param policies: 工具名到策略的映射
    :param mcp_approve_writes: MCP 写入是否需要确认
    :return:
    """
    prepared: list[ToolDefinition] = []
    for tool_def in tool_defs:
        policy = resolve_work_tool_policy(
            tool_def=tool_def,
            policies=policies,
            mcp_approve_writes=mcp_approve_writes,
        )
        if policy == AIBuddyToolPolicy.deny:
            continue
        prepared.append(replace(tool_def, defer_loading=True) if is_mcp_tool(tool_def) else tool_def)
    return prepared


async def build_runtime_hooks_capability(ctx: CapabilityContext) -> list[CapabilityResult]:  # ruff: ignore[unused-async]
    """
    构建观测、工具过滤与显式工具策略审批

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return []

    policies = ctx.forwarded_props.tool_policies or {}
    hooks = build_tool_policy_hooks(
        policies=policies,
        mcp_approve_writes=ctx.forwarded_props.mcp_approve_writes,
    )

    def prepare_tools(
        run_ctx: RunContext[ChatAgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """
        按本轮策略过滤工具，并延迟加载 MCP 工具

        :param run_ctx: 运行上下文
        :param tool_defs: 工具定义列表
        :return:
        """
        del run_ctx
        return prepare_work_tools(
            tool_defs=tool_defs,
            policies=policies,
            mcp_approve_writes=ctx.forwarded_props.mcp_approve_writes,
        )

    return [CapabilityResult(capability=hooks), CapabilityResult(capability=PrepareTools(prepare_tools))]
