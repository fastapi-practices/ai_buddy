from pydantic_ai import Agent
from pydantic_ai.capabilities import Caching
from pydantic_ai_harness.repair_tool_arguments import RepairToolArguments
from pydantic_ai_harness.subagents import SubAgent, SubAgents

from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.agent.work.capabilities.runtime_hooks import build_tool_policy_hooks
from backend.plugin.ai_buddy.agent.work.model_settings import build_model_settings
from backend.plugin.ai_buddy.agent.work.subagent_tools import build_subagent_toolset
from backend.plugin.ai_buddy.crud.crud_subagent import ai_buddy_subagent_dao
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
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
    if not catalog:
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
