import asyncio
import base64

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from mcp.types import Tool
from pydantic_ai.mcp import MCPToolset
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.mcp import build_mcp_toolset
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.model.mcp import AIBuddyMcp
from backend.plugin.ai_buddy.schema.mcp_app import (
    AIBuddyMcpAppScope,
    CallAIBuddyMcpAppToolParam,
    GetAIBuddyMcpAppDetail,
    GetAIBuddyMcpAppToolInfoDetail,
)
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.service.mcp_service import ai_buddy_mcp_service
from backend.plugin.ai_buddy.utils.mcp_app import ui_resource_uri


class AIBuddyMcpAppService:
    """MCP 应用资源与工具调用服务类"""

    @asynccontextmanager
    async def session(
        self, *, db: AsyncSession, conversation_id: str, user_id: int, is_superuser: bool, scope: AIBuddyMcpAppScope
    ) -> AsyncGenerator[tuple[AIBuddyMcp, MCPToolset, list[Tool]], None]:
        """
        校验会话与工具权限并管理 MCP 客户端连接

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为超级管理员
        :param scope: MCP 应用访问范围
        :return:
        """
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=conversation_id, user_id=user_id
        )
        message = await ai_buddy_message_dao.get_latest_user(db, conversation_id)
        context = message.turn_context if message and isinstance(message.turn_context, dict) else {}
        enabled_mcp_ids = {
            value for value in context.get('mcp_ids', []) if isinstance(value, int) and not isinstance(value, bool)
        }
        if scope.mcp_id not in enabled_mcp_ids:
            raise errors.ForbiddenError(msg='当前会话未启用此 MCP')
        servers = await ai_buddy_mcp_service.get_by_ids(
            db=db, mcp_ids=[scope.mcp_id], user_id=user_id, is_superuser=is_superuser
        )
        if not servers:
            raise errors.NotFoundError(msg='MCP 不存在')
        server = servers[0]
        async with asyncio.timeout(max(1, min(server.read_timeout, 300))):
            async with await build_mcp_toolset(mcp=server, user_id=user_id) as session:
                tools = await session.list_tools()
                self._validate_app_tool(tools=tools, scope=scope)
                yield server, session, tools

    async def read_resource(
        self, *, db: AsyncSession, conversation_id: str, user_id: int, is_superuser: bool, scope: AIBuddyMcpAppScope
    ) -> GetAIBuddyMcpAppDetail:
        """
        读取当前会话获准访问的 MCP 应用资源

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为超级管理员
        :param scope: MCP 应用访问范围
        :return:
        """
        async with self.session(
            db=db, conversation_id=conversation_id, user_id=user_id, is_superuser=is_superuser, scope=scope
        ) as (server, session, _):
            result = await session.read_resource_for_app(scope.resource_uri)
            resource = next(
                (
                    item
                    for item in result['contents']
                    if item.get('uri') == scope.resource_uri
                    and (item.get('mimeType') or '').split(';', 1)[0].strip().lower() == 'text/html'
                ),
                None,
            )
            if resource is None:
                raise errors.RequestError(msg='MCP 未返回有效的 HTML 应用资源')
            if isinstance(resource.get('text'), str):
                html = resource['text']
            else:
                try:
                    html = base64.b64decode(resource.get('blob', ''), validate=True).decode('utf-8')
                except (ValueError, TypeError, UnicodeDecodeError) as exc:
                    raise errors.RequestError(msg='MCP 应用资源编码无效') from exc
            if len(html.encode('utf-8')) > 2 * 1024 * 1024:
                raise errors.RequestError(msg='MCP 应用资源超过 2 MB')
            return GetAIBuddyMcpAppDetail(html=html, metadata=resource.get('_meta') or {}, server_name=server.name)

    async def tool_info(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        is_superuser: bool,
        obj: CallAIBuddyMcpAppToolParam,
    ) -> GetAIBuddyMcpAppToolInfoDetail:
        """
        获取 MCP 应用工具信息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为超级管理员
        :param obj: MCP 应用工具调用参数
        :return:
        """
        async with self.session(
            db=db, conversation_id=conversation_id, user_id=user_id, is_superuser=is_superuser, scope=obj
        ) as (_, _, tools):
            target = self._validate_app_tool(tools=tools, scope=obj, name=obj.name)
            return GetAIBuddyMcpAppToolInfoDetail(
                name=target.name, title=target.title or target.name, read_only=self._read_only_tool(tool=target)
            )

    async def call_tool(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        is_superuser: bool,
        obj: CallAIBuddyMcpAppToolParam,
    ) -> dict[str, Any]:
        """
        在权限与审批通过后调用 MCP 应用工具

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为超级管理员
        :param obj: MCP 应用工具调用参数
        :return:
        """
        async with self.session(
            db=db, conversation_id=conversation_id, user_id=user_id, is_superuser=is_superuser, scope=obj
        ) as (_, session, tools):
            target = self._validate_app_tool(tools=tools, scope=obj, name=obj.name)
            if not self._read_only_tool(tool=target) and not obj.approved:
                raise errors.ForbiddenError(msg='需要用户批准此次 MCP 应用工具调用')
            return await session.call_tool_for_app(obj.name, obj.arguments)

    @staticmethod
    def _validate_app_tool(*, tools: list[Tool], scope: AIBuddyMcpAppScope, name: str | None = None) -> Tool:
        """
        资源必须来自当前服务声明，调用仅允许暴露给应用的工具

        :param tools: MCP 工具声明列表
        :param scope: MCP 应用访问范围
        :param name: 待调用的工具名称
        :return:
        """
        origin = next((tool for tool in tools if tool.name == scope.tool_name), None)
        if not origin or ui_resource_uri(origin.meta) != scope.resource_uri:
            raise errors.ForbiddenError(msg='该工具未声明请求的 MCP 应用资源')
        target = next((tool for tool in tools if tool.name == (name or scope.tool_name)), None)
        if not target:
            raise errors.NotFoundError(msg='MCP 工具不存在')
        ui = (target.meta or {}).get('ui', {})
        if name is not None and isinstance(ui, dict) and 'visibility' in ui and 'app' not in ui['visibility']:
            raise errors.ForbiddenError(msg='该工具未对 MCP 应用开放')
        return target

    @staticmethod
    def _read_only_tool(*, tool: Tool) -> bool:
        """
        读取 MCP 工具的只读声明

        :param tool: MCP 工具声明
        :return:
        """
        if not tool.annotations:
            return False
        return bool(tool.annotations.read_only_hint)


ai_buddy_mcp_app_service = AIBuddyMcpAppService()
