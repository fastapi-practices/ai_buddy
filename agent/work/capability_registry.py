from collections.abc import Sequence
from dataclasses import replace
from inspect import isawaitable
from typing import TYPE_CHECKING, Any

from backend.plugin.ai_buddy.agent.work.capabilities.advisor import build_advisor_capability
from backend.plugin.ai_buddy.agent.work.capabilities.base import CapabilityBuilder
from backend.plugin.ai_buddy.agent.work.capabilities.builtin_toolset import build_builtin_toolset_capability
from backend.plugin.ai_buddy.agent.work.capabilities.compaction import (
    build_compact_on_request_capability,
    build_compaction_capability,
)
from backend.plugin.ai_buddy.agent.work.capabilities.files import build_file_understanding_capability
from backend.plugin.ai_buddy.agent.work.capabilities.guardrails import build_guardrail_capabilities
from backend.plugin.ai_buddy.agent.work.capabilities.mcp import build_mcp_capability
from backend.plugin.ai_buddy.agent.work.capabilities.memory import build_memory_capability
from backend.plugin.ai_buddy.agent.work.capabilities.office_attachments import build_office_attachments_capability
from backend.plugin.ai_buddy.agent.work.capabilities.planning import build_planning_capability
from backend.plugin.ai_buddy.agent.work.capabilities.project import build_project_capability
from backend.plugin.ai_buddy.agent.work.capabilities.reminders import build_reminder_capabilities
from backend.plugin.ai_buddy.agent.work.capabilities.resource_tools import build_resource_tools_capability
from backend.plugin.ai_buddy.agent.work.capabilities.runtime_hooks import build_runtime_hooks_capability
from backend.plugin.ai_buddy.agent.work.capabilities.sandbox import build_sandbox_capabilities
from backend.plugin.ai_buddy.agent.work.capabilities.sandbox_tools import build_sandbox_tools_capability
from backend.plugin.ai_buddy.agent.work.capabilities.search import build_search_capabilities
from backend.plugin.ai_buddy.agent.work.capabilities.skills import build_skills_capability
from backend.plugin.ai_buddy.agent.work.capabilities.subagents import build_subagents_capability
from backend.plugin.ai_buddy.agent.work.capabilities.tool_output_limits import build_tool_output_limits_capability
from backend.plugin.ai_buddy.agent.work.capabilities.user_input import build_user_input_capability
from backend.plugin.ai_buddy.agent.work.capabilities.work_context import build_work_context_capability
from backend.plugin.ai_buddy.agent.work.capabilities.workspace import build_workspace_capability
from backend.plugin.ai_buddy.agent.work.capabilities.workspace_tools import build_workspace_tools_capability
from backend.plugin.ai_buddy.dataclasses import (
    CapabilityAssembly,
    CapabilityContext,
    CapabilityRegistration,
    CapabilityResult,
)
from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyCapabilityScope
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam, AIBuddyForwardedPropsParam

if TYPE_CHECKING:
    from pydantic_ai.capabilities import AbstractCapability

CAPABILITY_REGISTRY: tuple[CapabilityRegistration, ...] = (
    # Office 附件必须先于通用文件理解处理
    CapabilityRegistration(builder=build_office_attachments_capability, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_file_understanding_capability, scope=AIBuddyCapabilityScope.all),
    # 压缩先更新持久历史，提醒和记忆随后只注入当前请求
    CapabilityRegistration(builder=build_compaction_capability, scope=AIBuddyCapabilityScope.all),
    CapabilityRegistration(builder=build_guardrail_capabilities, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_work_context_capability, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_project_capability, scope=AIBuddyCapabilityScope.all),
    CapabilityRegistration(builder=build_reminder_capabilities, scope=AIBuddyCapabilityScope.work_only),
    CapabilityRegistration(builder=build_memory_capability, scope=AIBuddyCapabilityScope.all),
    CapabilityRegistration(builder=build_skills_capability, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_workspace_capability, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_workspace_tools_capability, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_sandbox_tools_capability, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_resource_tools_capability, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_user_input_capability, scope=AIBuddyCapabilityScope.work_only),
    CapabilityRegistration(builder=build_mcp_capability, scope=AIBuddyCapabilityScope.all),
    CapabilityRegistration(builder=build_runtime_hooks_capability, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_search_capabilities, scope=AIBuddyCapabilityScope.all),
    CapabilityRegistration(builder=build_advisor_capability, scope=AIBuddyCapabilityScope.work_only),
    CapabilityRegistration(builder=build_builtin_toolset_capability, scope=AIBuddyCapabilityScope.chat_and_work),
    CapabilityRegistration(builder=build_planning_capability, scope=AIBuddyCapabilityScope.work_and_coding),
    CapabilityRegistration(builder=build_subagents_capability, scope=AIBuddyCapabilityScope.work_and_coding),
    CapabilityRegistration(builder=build_sandbox_capabilities, scope=AIBuddyCapabilityScope.work_only),
    CapabilityRegistration(builder=build_compact_on_request_capability, scope=AIBuddyCapabilityScope.work_only),
    CapabilityRegistration(builder=build_tool_output_limits_capability, scope=AIBuddyCapabilityScope.chat_and_work),
)

# coding 模式沿用原有的能力执行顺序，其他模式直接使用注册表顺序
CAPABILITY_PROFILE_ORDER: dict[AIBuddyAgentMode, tuple[CapabilityBuilder, ...]] = {
    AIBuddyAgentMode.coding: (
        build_file_understanding_capability,
        build_compaction_capability,
        build_mcp_capability,
        build_memory_capability,
        build_project_capability,
        build_planning_capability,
        build_search_capabilities,
        build_subagents_capability,
    ),
}


def resolve_capability_mode(forwarded_props: AIBuddyForwardedPropsParam) -> AIBuddyAgentMode:
    """
    将请求参数解析为能力装配模式，生图请求沿用工作模式的安全边界

    :param forwarded_props: 本轮扩展参数
    :return:
    """
    if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam):
        return forwarded_props.agent_mode
    return AIBuddyAgentMode.work


def capability_registrations_for(mode: AIBuddyAgentMode) -> tuple[CapabilityRegistration, ...]:
    """
    按模式返回有序能力注册项

    :param mode: Agent 运行模式
    :return:
    """
    registrations = tuple(registration for registration in CAPABILITY_REGISTRY if mode in registration.scope.modes)
    profile_order = CAPABILITY_PROFILE_ORDER.get(mode)
    if profile_order is None:
        return registrations
    registrations_by_builder = {registration.builder: registration for registration in registrations}
    if len(profile_order) != len(registrations_by_builder) or set(profile_order) != set(registrations_by_builder):
        raise RuntimeError(f'{mode.value} 能力 profile 顺序与注册表不一致')

    return tuple(registrations_by_builder[builder] for builder in profile_order)


def capability_builders_for(mode: AIBuddyAgentMode) -> tuple[CapabilityBuilder, ...]:
    """
    按模式返回有序能力构建器

    :param mode: Agent 运行模式
    :return:
    """
    return tuple(registration.builder for registration in capability_registrations_for(mode))


async def build_profile_capabilities(*, mode: AIBuddyAgentMode, context: CapabilityContext) -> CapabilityAssembly:
    """
    执行模式对应的能力构建器并推进能力组合状态

    :param mode: Agent 运行模式
    :param context: 能力构建上下文
    :return:
    """
    capabilities: list[AbstractCapability[Any]] = []
    has_builtin_tools = context.has_builtin_tools
    has_function_tool_source = False
    for registration in capability_registrations_for(mode):
        builder_context = replace(context, has_builtin_tools=has_builtin_tools)
        outcomes = registration.builder(builder_context)
        if isawaitable(outcomes):
            outcomes = await outcomes
        normalized: Sequence[CapabilityResult] = outcomes if isinstance(outcomes, Sequence) else (outcomes,)
        for result in normalized:
            if result.capability is not None:
                capabilities.append(result.capability)
            has_builtin_tools = has_builtin_tools or result.introduces_builtin_tool
            has_function_tool_source = has_function_tool_source or result.introduces_function_tool_source
    return CapabilityAssembly(
        capabilities=tuple(capabilities),
        has_builtin_tools=has_builtin_tools,
        has_function_tool_source=has_function_tool_source,
    )
