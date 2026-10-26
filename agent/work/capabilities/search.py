from collections.abc import Sequence

from pydantic_ai.capabilities import Toolset, WebFetch, WebSearch, XSearch
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.common_tools.exa import ExaToolset
from pydantic_ai.common_tools.tavily import tavily_search_tool
from pydantic_ai.native_tools import WebFetchTool, WebSearchTool, XSearchTool
from pydantic_ai.toolsets import FunctionToolset

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed, native_builtin_allowed
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType, AIBuddyWebSearchType
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config


def _build_builtin_search(ctx: CapabilityContext) -> CapabilityResult:
    """只选择实际可用的搜索路径，禁止隐藏的函数工具后备绕过门禁

    :param ctx: 运行上下文
    :return:
    """
    use_native = (
        native_builtin_allowed(adapter=ctx.adapter) or not ctx.supports_tools
    ) and WebSearchTool in ctx.supported_native_tools
    if not use_native and not function_tools_allowed(
        adapter=ctx.adapter, supports_tools=ctx.supports_tools, has_builtin_tools=ctx.has_builtin_tools
    ):
        raise errors.RequestError(msg='当前模型不支持联网搜索，请更换模型或关闭联网搜索')
    return CapabilityResult(
        capability=WebSearch(native=use_native, local=False if use_native else duckduckgo_search_tool()),
        introduces_builtin_tool=use_native,
        introduces_function_tool_source=not use_native,
    )


async def build_search_capabilities(ctx: CapabilityContext) -> Sequence[CapabilityResult]:
    """
    构建联网搜索能力

    :param ctx: 能力构建上下文
    :return:
    """
    forwarded_props = ctx.forwarded_props
    web_search = forwarded_props.web_search
    results: list[CapabilityResult] = []
    match web_search:
        case AIBuddyWebSearchType.off:
            pass
        case AIBuddyWebSearchType.builtin:
            # Google 工作模式保留函数工具，使用内置搜索能力的本地后备实现
            results.append(_build_builtin_search(ctx))
        case AIBuddyWebSearchType.exa:
            await load_ai_buddy_config(ctx.db)
            if not settings.AI_BUDDY_EXA_API_KEY:
                raise errors.RequestError(msg='未配置 AI_BUDDY_EXA_API_KEY，无法启用 Exa 搜索')
            results.append(
                CapabilityResult(
                    capability=Toolset(ExaToolset(api_key=settings.AI_BUDDY_EXA_API_KEY)),
                    introduces_function_tool_source=True,
                )
            )
        case AIBuddyWebSearchType.tavily:
            await load_ai_buddy_config(ctx.db)
            if not settings.AI_BUDDY_TAVILY_API_KEY:
                raise errors.RequestError(msg='未配置 AI_BUDDY_TAVILY_API_KEY，无法启用 Tavily 搜索')
            results.append(
                CapabilityResult(
                    capability=Toolset(FunctionToolset([tavily_search_tool(api_key=settings.AI_BUDDY_TAVILY_API_KEY)])),
                    introduces_function_tool_source=True,
                )
            )
        case AIBuddyWebSearchType.duckduckgo:
            results.append(
                CapabilityResult(
                    capability=Toolset(FunctionToolset([duckduckgo_search_tool()])),
                    introduces_function_tool_source=True,
                )
            )
        case _:
            raise errors.RequestError(msg='不支持的网络搜索模式')

    native_fetch = native_builtin_allowed(adapter=ctx.adapter) and WebFetchTool in ctx.supported_native_tools
    local_fetch = function_tools_allowed(
        adapter=ctx.adapter, supports_tools=ctx.supports_tools, has_builtin_tools=ctx.has_builtin_tools
    )
    if ctx.forwarded_props.generation_type == AIBuddyChatGenerationType.text and (native_fetch or local_fetch):
        results.append(
            CapabilityResult(
                capability=WebFetch() if native_fetch else WebFetch(native=False, local=True),
                introduces_builtin_tool=native_fetch,
                introduces_function_tool_source=not native_fetch,
            )
        )
    if (
        ctx.forwarded_props.generation_type == AIBuddyChatGenerationType.text
        and native_builtin_allowed(adapter=ctx.adapter)
        and XSearchTool in ctx.supported_native_tools
    ):
        results.append(CapabilityResult(capability=XSearch(), introduces_builtin_tool=True))
    return tuple(results)
