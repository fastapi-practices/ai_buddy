from typing import Any

from fastmcp import Client
from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPToolset, SSETransport, StdioTransport, StreamableHttpTransport
from pydantic_ai.messages import ToolReturn
from pydantic_ai.toolsets.abstract import ToolsetTool

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.enums import AIBuddyMcpType
from backend.plugin.ai_buddy.model.mcp import AIBuddyMcp
from backend.plugin.ai_buddy.security.ssrf import create_public_http_client
from backend.plugin.ai_buddy.service.mcp_oauth_service import ai_buddy_mcp_oauth_service
from backend.plugin.ai_buddy.utils.mcp_app import UiExtension


class BuddyMCPToolset(MCPToolset):
    """在原生 MCP Apps 结果中附加宿主校验的服务来源"""

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: RunContext[Any], tool: ToolsetTool[Any]
    ) -> Any:
        """保留 SDK 多模态结果与应用元数据

        :param name: 工具名称
        :param tool_args: 工具参数
        :param ctx: 运行上下文
        :param tool: 工具定义
        :return:
        """
        result = await super().call_tool(name, tool_args, ctx, tool)
        if isinstance(result, ToolReturn) and isinstance(result.metadata, dict):
            app = result.metadata.get('mcp_app')
            if isinstance(app, dict):
                metadata = dict(app['result'].get('_meta') or {})
                metadata.pop('ui', None)
                metadata['fba/source'] = {'mcpId': int(self.id.removeprefix('mcp_')), 'toolName': name}
                app['result']['_meta'] = metadata
        return result


async def build_mcp_toolset(*, mcp: AIBuddyMcp, user_id: int) -> BuddyMCPToolset:
    """复用工作、编码与应用请求的 MCP 连接配置

    :param mcp: MCP 服务配置
    :param user_id: 当前用户 ID
    :return:
    """
    headers = await ai_buddy_mcp_oauth_service.headers(mcp=mcp, user_id=user_id)
    if mcp.type == AIBuddyMcpType.stdio:
        if not mcp.command:
            raise errors.RequestError(msg=f'MCP 缺少启动命令: {mcp.name}')
        transport = StdioTransport(
            command=mcp.command,
            args=mcp.args or [],
            env={str(key): str(value) for key, value in (mcp.env or {}).items()},
        )
    elif mcp.type == AIBuddyMcpType.sse:
        if not mcp.url:
            raise errors.RequestError(msg=f'MCP 缺少 SSE URL: {mcp.name}')
        transport = SSETransport(
            url=mcp.url,
            headers=headers,
            sse_read_timeout=mcp.read_timeout,
            httpx_client_factory=create_public_http_client,
        )
    else:
        if not mcp.url:
            raise errors.RequestError(msg=f'MCP 缺少 Streamable HTTP URL: {mcp.name}')
        transport = StreamableHttpTransport(
            url=mcp.url,
            headers=headers,
            httpx_client_factory=create_public_http_client,
        )
    return BuddyMCPToolset(
        Client(transport, init_timeout=mcp.timeout, timeout=mcp.read_timeout, extensions=[UiExtension()]),
        id=f'mcp_{mcp.id}',
        max_retries=settings.AI_BUDDY_MCP_MAX_RETRIES,
        include_instructions=mcp.include_instructions,
    )
