from dataclasses import replace
from typing import Any

from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.capabilities import AbstractCapability, PrepareTools
from pydantic_ai.capabilities.hooks import Hooks
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.tools import ToolDefinition
from pydantic_ai_harness.smart_search import SmartSearch

from backend.common.exception import errors
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.coding.protocol.base import CodingHostSpec, WaitApproval
from backend.plugin.ai_buddy.agent.coding.types import AgentToolCall
from backend.plugin.ai_buddy.agent.delegation import BuddyDelegationReports
from backend.plugin.ai_buddy.agent.models import auxiliary_model_name, bind_auxiliary_model
from backend.plugin.ai_buddy.agent.work.capability_registry import build_profile_capabilities
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyPermissionMode, AIBuddyToolPolicy
from backend.plugin.ai_buddy.provider.base import ProviderAdapter
from backend.plugin.ai_buddy.schema.chat import AIBuddyForwardedPropsParam
from backend.plugin.ai_buddy.security.tool_policy import is_mcp_tool, resolve_tool_policy_with_dependencies


async def build_coding_capabilities(
    *,
    spec: CodingHostSpec,
    model: Model,
    adapter: ProviderAdapter,
    bound_tool_names: frozenset[str],
    wait_approval: WaitApproval | None,
) -> list[AbstractCapability[Any]]:
    """
    复用工作模式资源能力，并接入编码运行审批

    :param spec: 编码宿主规格
    :param model: 当前供应商模型
    :param adapter: 供应商适配器
    :param bound_tool_names: 已自行执行审批的工具名
    :param wait_approval: 本轮审批等待
    :return:
    """
    if spec.forwarded_props is None:
        return []
    props = spec.forwarded_props.model_copy(deep=True)
    # 子代理不能挂起等待审批，保留写入门禁，交由主代理请求用户确认
    if spec.run_context.permission_mode == AIBuddyPermissionMode.ask:
        props.tool_policies = {'write_artifact': AIBuddyToolPolicy.ask, **(props.tool_policies or {})}
    capabilities: list[AbstractCapability[Any]] = []
    if props.background_subagents_enabled:
        capabilities.append(BuddyDelegationReports(conversation_id=spec.run_context.conversation_id))
    async with async_db_session() as db:
        ctx = CapabilityContext(
            db=db,
            adapter=adapter,
            forwarded_props=props,
            user_id=spec.run_context.user_id,
            is_superuser=spec.run_context.is_superuser,
            supports_tools=True,
            supported_native_tools=model.profile.get('supported_native_tools', frozenset()),
            supports_image_output=False,
            has_builtin_tools=False,
            model=model,
            conversation_id=spec.run_context.conversation_id,
            project_name=spec.run_context.project_name,
            conversation_goal=spec.run_context.goal,
            context_window=spec.context_window,
        )
        assembly = await build_profile_capabilities(mode=AIBuddyAgentMode.coding, context=ctx)
        capabilities.extend(assembly.capabilities)
        if props.smart_search_model:
            if spec.run_context.sandbox is None:
                raise errors.RequestError(msg='代码语义搜索需要已连接的工作区')
            search_model = await bind_auxiliary_model(ctx, auxiliary_model_name(ctx, props.smart_search_model))
            capabilities.append(SmartSearch(search_model, concurrency=2, cache_index=False))

    def prepare_tools(
        run_ctx: RunContext[ChatAgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """
        按本轮策略过滤编码工具，并延迟加载 MCP 工具

        :param run_ctx: 运行上下文
        :param tool_defs: 工具定义列表
        :return:
        """
        del run_ctx
        return prepare_coding_tools(
            tool_defs=tool_defs,
            policies=props.tool_policies or {},
            mcp_approve_writes=props.mcp_approve_writes,
        )

    capabilities.extend((
        PrepareTools(prepare_tools),
        _build_resource_policy_hooks(
            spec=spec, props=props, bound_tool_names=bound_tool_names, wait_approval=wait_approval
        ),
    ))
    return capabilities


def prepare_coding_tools(
    *,
    tool_defs: list[ToolDefinition],
    policies: dict[str, str],
    mcp_approve_writes: bool,
) -> list[ToolDefinition]:
    """
    隐藏显式拒绝的编码工具，并延迟暴露 MCP 工具

    :param tool_defs: 本轮工具定义
    :param policies: 工具名到策略的映射
    :param mcp_approve_writes: MCP 写入是否需要确认
    :return:
    """
    prepared: list[ToolDefinition] = []
    for tool_def in tool_defs:
        is_mcp = is_mcp_tool(tool_def)
        default = AIBuddyToolPolicy.ask if is_mcp and mcp_approve_writes else AIBuddyToolPolicy.allow
        policy = resolve_tool_policy_with_dependencies(
            tool_name=tool_def.name,
            policies=policies,
            default=default,
        )
        if policy == AIBuddyToolPolicy.deny:
            continue
        prepared.append(replace(tool_def, defer_loading=True) if is_mcp else tool_def)
    return prepared


def _build_resource_policy_hooks(
    *,
    spec: CodingHostSpec,
    props: AIBuddyForwardedPropsParam,
    bound_tool_names: frozenset[str],
    wait_approval: WaitApproval | None,
) -> Hooks[ChatAgentDeps]:
    """
    构建新增资源工具的审批与拒绝策略

    :param spec: 编码宿主规格
    :param props: 本轮聊天扩展参数
    :param bound_tool_names: 已自行执行审批的工具名
    :param wait_approval: 本轮审批等待
    :return:
    """
    hooks = Hooks(id='coding-resource-policy')

    @hooks.on.before_tool_execute
    async def approve_resource_tool(
        ctx: RunContext[ChatAgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: object,
    ) -> object:
        """
        对新增资源工具应用同一轮策略，拒绝不会产生副作用

        :param ctx: 模型运行上下文
        :param call: 工具调用
        :param tool_def: 工具定义
        :param args: 已校验参数
        :return:
        """
        del ctx
        if call.tool_name in bound_tool_names:
            return args
        is_mcp = (tool_def.metadata or {}).get('ai_buddy_source') == 'mcp'
        mutating = is_mcp or call.tool_name in {'write_memory', 'delete_memory', 'edit_memory'}
        default = (
            AIBuddyToolPolicy.ask
            if (mutating and spec.run_context.permission_mode == AIBuddyPermissionMode.ask)
            or (is_mcp and props.mcp_approve_writes)
            else AIBuddyToolPolicy.allow
        )
        dependency_defaults = (
            {'bash': AIBuddyToolPolicy.ask} if spec.run_context.permission_mode == AIBuddyPermissionMode.ask else None
        )
        policy = resolve_tool_policy_with_dependencies(
            tool_name=call.tool_name,
            policies=props.tool_policies,
            default=default,
            dependency_defaults=dependency_defaults,
        )
        if call.tool_name == 'smart_search' and isinstance(args, dict):
            args = {**args, 'candidates': min(int(args.get('candidates', 16)), 32)}
        if policy == AIBuddyToolPolicy.deny:
            raise ModelRetry(f'工具已被拒绝: {call.tool_name}')
        if policy == AIBuddyToolPolicy.ask:
            approval = AgentToolCall(id=call.tool_call_id, name=call.tool_name, arguments=call.args_as_dict())
            if wait_approval is None or not await wait_approval(f'需要确认: {call.tool_name}', approval):
                raise ModelRetry('用户未批准此操作，工具未执行')
        return args

    return hooks
