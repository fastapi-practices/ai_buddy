from collections.abc import Sequence

from pydantic_ai.capabilities import Toolset

from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.mcp import build_mcp_toolset
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.service.mcp_service import ai_buddy_mcp_service
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config


async def build_mcp_capability(ctx: CapabilityContext) -> Sequence[CapabilityResult]:
    """
    构建带原生应用协议的 MCP 能力

    :param ctx: 能力构建上下文
    :return:
    """
    if not ctx.forwarded_props.mcp_ids:
        return ()
    if not ctx.supports_tools:
        raise errors.RequestError(msg='当前模型不支持工具，请更换模型或关闭 MCP')
    if ctx.user_id is None:
        raise errors.AuthorizationError(msg='当前调用缺少 MCP 用户身份')
    await load_ai_buddy_config(ctx.db)
    mcps = await ai_buddy_mcp_service.get_by_ids(
        db=ctx.db,
        mcp_ids=ctx.forwarded_props.mcp_ids,
        user_id=ctx.user_id,
        is_superuser=ctx.is_superuser,
    )
    results: list[CapabilityResult] = []
    for mcp in mcps:
        toolset = await build_mcp_toolset(mcp=mcp, user_id=ctx.user_id)
        tool_prefix = (mcp.tool_prefix or f'mcp_{mcp.id}').rstrip('_') or f'mcp_{mcp.id}'
        results.append(
            CapabilityResult(
                capability=Toolset(
                    toolset.prefixed(tool_prefix).with_metadata(ai_buddy_source='mcp', ai_buddy_mcp_id=mcp.id)
                ),
                introduces_function_tool_source=True,
            )
        )
    return tuple(results)
