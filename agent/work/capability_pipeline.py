from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from inspect import isawaitable
from typing import Any

from pydantic_ai.capabilities import (
    AbstractCapability,
    Caching,
    IncludeToolReturnSchemas,
    Instrumentation,
    RaiseContentFilterError,
    ReinjectSystemPrompt,
    SetToolMetadata,
    Thinking,
    UseThreadExecutor,
)
from pydantic_ai.models import Model
from pydantic_ai.native_tools import AbstractNativeTool
from pydantic_ai_harness.guardrails import ToolGuardrail
from pydantic_ai_harness.repair_tool_arguments import RepairToolArguments
from pydantic_ai_harness.step_persistence import StepPersistence
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.delegation import BuddyDelegationReports
from backend.plugin.ai_buddy.agent.step_store import ai_buddy_step_store
from backend.plugin.ai_buddy.agent.work.capabilities.advisor import build_advisor_capability
from backend.plugin.ai_buddy.agent.work.capabilities.base import CapabilityBuilder
from backend.plugin.ai_buddy.agent.work.capabilities.builtin_toolset import build_builtin_toolset_capability
from backend.plugin.ai_buddy.agent.work.capabilities.compaction import build_compaction_capability
from backend.plugin.ai_buddy.agent.work.capabilities.files import build_file_understanding_capability
from backend.plugin.ai_buddy.agent.work.capabilities.guardrails import build_guardrail_capabilities
from backend.plugin.ai_buddy.agent.work.capabilities.mcp import build_mcp_capability
from backend.plugin.ai_buddy.agent.work.capabilities.memory import build_memory_capability
from backend.plugin.ai_buddy.agent.work.capabilities.planning import build_planning_capability
from backend.plugin.ai_buddy.agent.work.capabilities.project import build_project_capability
from backend.plugin.ai_buddy.agent.work.capabilities.reminders import build_reminder_capabilities
from backend.plugin.ai_buddy.agent.work.capabilities.runtime_hooks import build_runtime_hooks_capability
from backend.plugin.ai_buddy.agent.work.capabilities.sandbox import build_sandbox_capabilities
from backend.plugin.ai_buddy.agent.work.capabilities.search import build_search_capabilities
from backend.plugin.ai_buddy.agent.work.capabilities.skills import build_skills_capability
from backend.plugin.ai_buddy.agent.work.capabilities.subagents import build_subagents_capability
from backend.plugin.ai_buddy.agent.work.capabilities.tool_output_limits import build_tool_output_limits_capability
from backend.plugin.ai_buddy.agent.work.capabilities.user_input import build_user_input_capability
from backend.plugin.ai_buddy.agent.work.capabilities.work_context import build_work_context_capability
from backend.plugin.ai_buddy.agent.work.capabilities.workspace import build_workspace_capability
from backend.plugin.ai_buddy.agent.work.capabilities.workspace_tools import build_workspace_tools_capability
from backend.plugin.ai_buddy.dataclasses import CapabilityContext
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyChatGenerationType,
    AIBuddyChatThinkingType,
    AIBuddyModelCapability,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.provider.base import ProviderAdapter
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam, AIBuddyForwardedPropsParam
from backend.plugin.ai_buddy.security.jev import is_jev_tool_risk
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service

_TOOL_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.AI_BUDDY_AGENT_THREAD_EXECUTOR_MAX_WORKERS, thread_name_prefix='ai_buddy_tool'
)

_CAPABILITY_BUILDERS: tuple[CapabilityBuilder, ...] = (
    build_file_understanding_capability,
    # 压缩先更新持久历史，提醒和记忆随后仅注入当前请求
    build_compaction_capability,
    build_guardrail_capabilities,
    build_work_context_capability,
    build_project_capability,
    build_reminder_capabilities,
    build_memory_capability,
    build_skills_capability,
    build_workspace_capability,
    build_workspace_tools_capability,
    build_user_input_capability,
    build_mcp_capability,
    build_runtime_hooks_capability,
    build_search_capabilities,
    build_advisor_capability,
    build_builtin_toolset_capability,
    build_planning_capability,
    build_subagents_capability,
    build_sandbox_capabilities,
    build_tool_output_limits_capability,
)


async def assemble_capabilities(
    *,
    db: AsyncSession,
    adapter: ProviderAdapter,
    forwarded_props: AIBuddyForwardedPropsParam,
    user_id: int | None,
    is_superuser: bool,
    supports_tools: bool,
    supported_native_tools: frozenset[type[AbstractNativeTool]],
    supports_image_output: bool,
    model: Model | None = None,
    conversation_id: str | None = None,
    assistant_id: int | None = None,
    context_window: int | None = None,
    catalog_capabilities: frozenset[AIBuddyModelCapability] = frozenset(),
) -> list[AbstractCapability[Any]]:
    """
    按顺序运行 capability 构建器并校验能力组合

    :param db: 数据库会话
    :param adapter: 供应商适配器
    :param forwarded_props: 聊天扩展参数
    :param user_id: 用户 ID
    :param is_superuser: 是否为超级管理员
    :param supports_tools: 是否支持函数工具
    :param supported_native_tools: 支持的原生工具集合
    :param supports_image_output: 是否支持图片输出
    :param model: 当前模型实例
    :param conversation_id: 对话 ID
    :param assistant_id: 新建对话时的助手 ID
    :param context_window: 模型上下文窗口 token 数
    :param catalog_capabilities: 后台配置的模型能力
    :return:
    """
    (
        conversation_goal,
        project_name,
        assistant_name,
        assistant_prompt,
    ) = await ai_buddy_conversation_service.get_workspace_context(
        db=db,
        user_id=user_id,
        conversation_id=conversation_id,
        assistant_id=assistant_id,
    )

    capabilities: list[AbstractCapability[Any]] = []
    thinking = forwarded_props.thinking
    if thinking is not None and AIBuddyModelCapability.thinking in catalog_capabilities:
        thinking_effort = False if thinking == AIBuddyChatThinkingType.off else thinking
        capabilities.append(Thinking(thinking_effort))
    capabilities.append(RaiseContentFilterError())
    if forwarded_props.generation_type == AIBuddyChatGenerationType.text:
        capabilities.append(Caching(forwarded_props.cache_enabled))
        if (
            forwarded_props.background_subagents_enabled
            and conversation_id
            and forwarded_props.agent_mode != AIBuddyAgentMode.chat
        ):
            capabilities.append(BuddyDelegationReports(conversation_id=conversation_id))
        capabilities.append(RepairToolArguments())
    capabilities.extend(
        _build_runtime_capabilities(text=forwarded_props.generation_type == AIBuddyChatGenerationType.text)
    )

    has_builtin = False
    has_fn_source = False
    chat = (
        isinstance(forwarded_props, AIBuddyChatForwardedPropsParam)
        and forwarded_props.agent_mode == AIBuddyAgentMode.chat
    )
    for builder in _CAPABILITY_BUILDERS:
        if chat and builder in (
            build_reminder_capabilities,
            build_user_input_capability,
            build_advisor_capability,
            build_planning_capability,
            build_subagents_capability,
            build_sandbox_capabilities,
        ):
            continue
        ctx = CapabilityContext(
            db=db,
            adapter=adapter,
            forwarded_props=forwarded_props,
            user_id=user_id,
            is_superuser=is_superuser,
            supports_tools=supports_tools,
            supported_native_tools=supported_native_tools,
            supports_image_output=supports_image_output,
            has_builtin_tools=has_builtin,
            model=model,
            conversation_id=conversation_id,
            conversation_goal=conversation_goal,
            project_name=project_name,
            assistant_name=assistant_name,
            assistant_prompt=assistant_prompt,
            context_window=context_window,
            catalog_capabilities=catalog_capabilities,
        )
        outcomes = builder(ctx)
        if isawaitable(outcomes):
            outcomes = await outcomes
        normalized: Sequence[Any] = outcomes if isinstance(outcomes, Sequence) else (outcomes,)
        for result in normalized:
            if result.capability is not None:
                capabilities.append(result.capability)
            has_builtin = has_builtin or result.introduces_builtin_tool
            has_fn_source = has_fn_source or result.introduces_function_tool_source

    validate_capability_mix(
        has_fn_source=has_fn_source,
        supports_tools=supports_tools,
        provider_type=adapter.provider_type,
        has_builtin=has_builtin,
    )
    return _order_tool_result_filters(capabilities)


def _build_runtime_capabilities(*, text: bool) -> list[AbstractCapability[Any]]:
    """按配置构建 SDK 运行时能力

    :param text: 是否为文本生成
    :return:
    """
    capabilities: list[AbstractCapability[Any]] = []
    if text:
        capabilities.extend((
            ReinjectSystemPrompt(),
            UseThreadExecutor(_TOOL_EXECUTOR),
            SetToolMetadata(tools=lambda _ctx, tool_def: is_jev_tool_risk(tool_def.name), ai_buddy_high_risk=True),
        ))
        if settings.AI_BUDDY_AGENT_STEP_PERSISTENCE_ENABLED:
            capabilities.append(StepPersistence(store=ai_buddy_step_store, agent_name='ai_buddy_work'))
        if settings.AI_BUDDY_AGENT_INCLUDE_TOOL_RETURN_SCHEMAS:
            capabilities.append(IncludeToolReturnSchemas())
    if settings.AI_BUDDY_AGENT_INSTRUMENTATION_ENABLED:
        capabilities.append(Instrumentation())
    return capabilities


def _order_tool_result_filters(capabilities: list[AbstractCapability[Any]]) -> list[AbstractCapability[Any]]:
    """结果钩子逆序执行，将外溢放在守卫前以先清洗再落盘

    :param capabilities: 模型能力集合
    :return:
    """
    ordered: list[AbstractCapability[Any]] = []
    for capability in capabilities:
        if isinstance(capability, ToolOutputLimits):
            index = next(
                (index for index, existing in enumerate(ordered) if isinstance(existing, ToolGuardrail)), len(ordered)
            )
            ordered.insert(index, capability)
        else:
            ordered.append(capability)
    return ordered


def validate_capability_mix(
    *,
    has_fn_source: bool,
    supports_tools: bool,
    provider_type: AIBuddyProviderType,
    has_builtin: bool,
) -> None:
    """
    校验能力组合是否可同时启用

    :param has_fn_source: 是否引入函数工具源
    :param supports_tools: 模型是否支持函数工具
    :param provider_type: 供应商类型
    :param has_builtin: 是否引入内置工具
    :return:
    """
    if has_fn_source and not supports_tools:
        raise errors.RequestError(msg='当前模型不支持函数工具，请更换模型或关闭 MCP 与本地搜索')
    if has_fn_source and provider_type == AIBuddyProviderType.google and has_builtin:
        raise errors.RequestError(msg='Google 模型不支持同时使用原生工具和函数工具，请将联网搜索改为非内置模式')
