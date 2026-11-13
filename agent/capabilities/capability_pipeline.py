from concurrent.futures import ThreadPoolExecutor
from typing import Any

from pydantic_ai.capabilities import (
    AbstractCapability,
    Caching,
    IncludeToolReturnSchemas,
    Instrumentation,
    ModelFallback,
    RaiseContentFilterError,
    ReinjectSystemPrompt,
    SetToolMetadata,
    Thinking,
    UseThreadExecutor,
)
from pydantic_ai.models import Model
from pydantic_ai.native_tools import AbstractNativeTool
from pydantic_ai_harness import DetectLoops
from pydantic_ai_harness.guardrails import ToolGuardrail
from pydantic_ai_harness.repair_tool_arguments import RepairToolArguments
from pydantic_ai_harness.step_persistence import StepPersistence
from pydantic_ai_harness.tool_output_limits import ToolOutputLimits
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.capabilities.capability_registry import (
    build_profile_capabilities,
    resolve_capability_mode,
)
from backend.plugin.ai_buddy.agent.capabilities.extensions import build_extension_capabilities
from backend.plugin.ai_buddy.agent.delegation import BuddyDelegationReports
from backend.plugin.ai_buddy.agent.durability.config import DURABILITY_AGENT_NAME, step_persistence_enabled
from backend.plugin.ai_buddy.agent.step_store import ai_buddy_step_store
from backend.plugin.ai_buddy.dataclasses import CapabilityContext
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyChatGenerationType,
    AIBuddyChatThinkingType,
    AIBuddyModelCapability,
    AIBuddyOrigin,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.provider.base import ProviderAdapter
from backend.plugin.ai_buddy.schema.chat import AIBuddyForwardedPropsParam
from backend.plugin.ai_buddy.security.jev import is_jev_tool_risk
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service

_TOOL_EXECUTOR = ThreadPoolExecutor(
    max_workers=settings.AI_BUDDY_AGENT_THREAD_EXECUTOR_MAX_WORKERS, thread_name_prefix='ai_buddy_tool'
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
    fallback_models: list[Model] | None = None,
    conversation_id: str | None = None,
    assistant_id: int | None = None,
    context_window: int | None = None,
    catalog_capabilities: frozenset[AIBuddyModelCapability] = frozenset(),
    origin: AIBuddyOrigin = AIBuddyOrigin.web,
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
    :param fallback_models: 备用模型链，主模型失败时依次尝试
    :param conversation_id: 对话 ID
    :param assistant_id: 新建对话时的助手 ID
    :param context_window: 模型上下文窗口 token 数
    :param catalog_capabilities: 后台配置的模型能力
    :param origin: 本轮消息来源
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

    mode = resolve_capability_mode(forwarded_props)
    capabilities: list[AbstractCapability[Any]] = []
    text = forwarded_props.generation_type == AIBuddyChatGenerationType.text
    thinking = forwarded_props.thinking
    if thinking is not None and AIBuddyModelCapability.thinking in catalog_capabilities:
        thinking_effort = False if thinking == AIBuddyChatThinkingType.off else thinking
        capabilities.append(Thinking(thinking_effort))
    capabilities.append(RaiseContentFilterError())
    if fallback_models:
        capabilities.append(ModelFallback(*fallback_models))
    if text:
        capabilities.append(Caching(forwarded_props.cache_enabled))
        if forwarded_props.background_subagents_enabled and conversation_id and mode != AIBuddyAgentMode.chat:
            capabilities.append(BuddyDelegationReports(conversation_id=conversation_id))
        capabilities.append(RepairToolArguments())
        capabilities.extend((
            ReinjectSystemPrompt(),
            UseThreadExecutor(_TOOL_EXECUTOR),
            SetToolMetadata(tools=lambda _ctx, tool_def: is_jev_tool_risk(tool_def.name), ai_buddy_high_risk=True),
            DetectLoops(),
        ))
        if step_persistence_enabled(forwarded_props):
            capabilities.append(StepPersistence(store=ai_buddy_step_store, agent_name=DURABILITY_AGENT_NAME))
        if settings.AI_BUDDY_AGENT_INCLUDE_TOOL_RETURN_SCHEMAS:
            capabilities.append(IncludeToolReturnSchemas())
    if settings.AI_BUDDY_AGENT_INSTRUMENTATION_ENABLED:
        capabilities.append(Instrumentation())

    context = CapabilityContext(
        db=db,
        adapter=adapter,
        forwarded_props=forwarded_props,
        user_id=user_id,
        is_superuser=is_superuser,
        supports_tools=supports_tools,
        supported_native_tools=supported_native_tools,
        supports_image_output=supports_image_output,
        has_builtin_tools=False,
        model=model,
        conversation_id=conversation_id,
        conversation_goal=conversation_goal,
        project_name=project_name,
        assistant_name=assistant_name,
        assistant_prompt=assistant_prompt,
        context_window=context_window,
        catalog_capabilities=catalog_capabilities,
        origin=origin,
    )
    assembly = await build_profile_capabilities(mode=mode, context=context)
    capabilities.extend(assembly.capabilities)
    extension_results = await build_extension_capabilities(context=context)
    capabilities.extend(result.capability for result in extension_results if result.capability is not None)

    _validate_capability_mix(
        has_fn_source=assembly.has_function_tool_source,
        supports_tools=supports_tools,
        provider_type=adapter.provider_type,
        has_builtin=assembly.has_builtin_tools,
    )

    # 结果钩子逆序执行，将输出限制放在守卫前以先清洗再落盘
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


def _validate_capability_mix(
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
