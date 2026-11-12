from typing import Any

from pydantic_ai import Agent
from pydantic_ai.capabilities import Caching
from pydantic_ai_harness.repair_tool_arguments import RepairToolArguments
from pydantic_ai_harness.subagents import DynamicAgentSpec, DynamicAgents, SubAgent, SubAgents, TaskControl

from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.agent.capabilities.runtime_hooks import build_tool_policy_hooks
from backend.plugin.ai_buddy.agent.work.model_settings import build_model_settings
from backend.plugin.ai_buddy.agent.work.subagent_tools import build_subagent_toolset
from backend.plugin.ai_buddy.crud.crud_subagent import ai_buddy_subagent_dao
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam
from backend.plugin.ai_buddy.security.jev import build_jev_capabilities
from backend.plugin.ai_buddy.utils.run_timeout import resolve_run_timeout


async def build_subagents_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    按子代理目录装配本轮子代理

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.model is None:
        return CapabilityResult(capability=None)
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return CapabilityResult(capability=None)
    if not function_tools_allowed(
        adapter=ctx.adapter,
        supports_tools=ctx.supports_tools,
        has_builtin_tools=ctx.has_builtin_tools,
    ):
        return CapabilityResult(capability=None)

    catalog = []
    if ctx.user_id is not None:
        catalog = list(await ai_buddy_subagent_dao.get_all(ctx.db, ctx.user_id))
    dynamic_agents = _build_dynamic_agents(ctx)
    if not catalog and dynamic_agents is None:
        return CapabilityResult(capability=None)
    agents = [
        SubAgent(
            Agent(
                ctx.model,
                name=item.name,
                deps_type=ChatAgentDeps,
                instructions=item.prompt,
                toolsets=[build_subagent_toolset()],
                model_settings=build_model_settings(adapter=ctx.adapter, forwarded_props=ctx.forwarded_props),
                capabilities=[Caching(ctx.forwarded_props.cache_enabled)],
            ),
            description=item.description,
            timeout_seconds=resolve_run_timeout(ctx.forwarded_props.run_timeout),
        )
        for item in catalog
    ]
    return CapabilityResult(
        capability=SubAgents(
            agents=agents,
            inherit_tools=False,
            dynamic_agents=dynamic_agents,
            task_control=_build_task_control(ctx),
            shared_capabilities=[
                RepairToolArguments(),
                *build_jev_capabilities(allow_ask=False),
                build_tool_policy_hooks(
                    policies=ctx.forwarded_props.tool_policies or {},
                    mcp_approve_writes=ctx.forwarded_props.mcp_approve_writes,
                    allow_ask=False,
                ),
            ],
        ),
        introduces_function_tool_source=True,
    )


def _build_dynamic_agents(ctx: CapabilityContext) -> DynamicAgents[ChatAgentDeps] | None:
    """
    构建运行期动态子代理能力，模型可按需创建临时子代理

    :param ctx: 能力构建上下文
    :return:
    """
    if not settings.AI_BUDDY_AGENT_DYNAMIC_SUBAGENTS_ENABLED:
        return None

    def build_agent(spec: DynamicAgentSpec) -> Agent[ChatAgentDeps, Any]:
        """
        按模型给出的设定构建临时子代理

        :param spec: 动态子代理设定
        :return:
        """
        return Agent(
            ctx.model,
            name=spec.name,
            description=spec.description,
            deps_type=ChatAgentDeps,
            instructions=spec.instructions,
            toolsets=[build_subagent_toolset()],
            model_settings=build_model_settings(adapter=ctx.adapter, forwarded_props=ctx.forwarded_props),
            capabilities=[Caching(ctx.forwarded_props.cache_enabled)],
        )

    return DynamicAgents(max_agents=settings.AI_BUDDY_AGENT_DYNAMIC_SUBAGENTS_MAX, factory=build_agent)


def _build_task_control(ctx: CapabilityContext) -> TaskControl | None:
    """
    构建子任务管控能力，仅在后台子代理所有者已绑定时开启

    :param ctx: 能力构建上下文
    :return:
    """
    if not isinstance(ctx.forwarded_props, AIBuddyChatForwardedPropsParam):
        return None
    if not ctx.forwarded_props.background_subagents_enabled or not ctx.conversation_id:
        return None
    return TaskControl()
