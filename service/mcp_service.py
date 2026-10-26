import secrets

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.ai_buddy.crud.crud_mcp import ai_buddy_mcp_dao
from backend.plugin.ai_buddy.crud.crud_mcp_oauth import ai_buddy_mcp_oauth_dao
from backend.plugin.ai_buddy.crud.crud_mcp_oauth_config import ai_buddy_mcp_oauth_config_dao
from backend.plugin.ai_buddy.enums import AIBuddyMcpType
from backend.plugin.ai_buddy.model import AIBuddyMcp
from backend.plugin.ai_buddy.schema.mcp import (
    CreateAIBuddyMcpParam,
    ImportAIBuddyMcpResult,
    UpdateAIBuddyMcpParam,
)
from backend.plugin.ai_buddy.security.ssrf import validate_public_http_url
from backend.plugin.ai_buddy.utils.mcp_import import parse_mcp_servers_json
from backend.plugin.ai_buddy.utils.sensitive_data import restore_masked_sensitive_data
from backend.utils.pattern_validate import match_string


class AIBuddyMcpService:
    """AI MCP 服务类"""

    @staticmethod
    def _normalize_transport_fields(
        *,
        obj: CreateAIBuddyMcpParam | UpdateAIBuddyMcpParam,
    ) -> CreateAIBuddyMcpParam | UpdateAIBuddyMcpParam:
        """
        规范化 MCP 传输相关字段

        :param obj: 创建或更新 MCP 参数
        :return:
        """
        command = (obj.command or '').strip()
        url = str(obj.url).strip() if obj.url else None

        if obj.type == AIBuddyMcpType.stdio:
            if not command:
                raise errors.RequestError(msg='stdio 类型 MCP 必须填写启动命令')
            return obj.model_copy(update={'command': command, 'url': None, 'headers': None})
        if obj.type in (AIBuddyMcpType.sse, AIBuddyMcpType.streamable_http):
            if not url:
                raise errors.RequestError(msg='sse/streamable_http 类型 MCP 必须填写 URL')
            validate_public_http_url(url)
            return obj.model_copy(update={'command': None, 'args': None, 'env': None, 'url': url})
        raise errors.RequestError(msg='不支持的 MCP 类型')

    @staticmethod
    def _validate_transport_permission(*, type: AIBuddyMcpType, is_superuser: bool) -> None:
        """
        校验 MCP 传输类型的执行权限

        :param type: MCP 类型
        :param is_superuser: 是否为超级管理员
        :return:
        """
        if type == AIBuddyMcpType.stdio and not is_superuser:
            raise errors.AuthorizationError(msg='仅超级管理员可以使用 stdio MCP')

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int, is_superuser: bool = False) -> Sequence[AIBuddyMcp]:
        """
        获取所有 MCP

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员，普通用户不返回 stdio
        :return:
        """
        mcps = await ai_buddy_mcp_dao.get_all(db, user_id)
        if is_superuser:
            return mcps
        return [item for item in mcps if item.type != AIBuddyMcpType.stdio]

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False) -> AIBuddyMcp:
        """
        获取 MCP

        :param db: 数据库会话
        :param pk: MCP ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        mcp = await ai_buddy_mcp_dao.get(db, pk, None if is_superuser else user_id)
        if not mcp:
            raise errors.NotFoundError(msg='MCP 不存在')
        return mcp

    async def get_by_ids(
        self,
        *,
        db: AsyncSession,
        mcp_ids: list[int],
        user_id: int,
        is_superuser: bool,
    ) -> Sequence[AIBuddyMcp]:
        """
        通过 ID 列表获取 MCP

        :param db: 数据库会话
        :param mcp_ids: MCP ID 列表
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        unique_ids = list(dict.fromkeys(mcp_ids))
        if len(unique_ids) != len(mcp_ids):
            raise errors.RequestError(msg='MCP ID 列表中存在重复项')
        mcps = await ai_buddy_mcp_dao.get_by_ids(db, unique_ids, user_id)
        if len(mcps) != len(unique_ids):
            raise errors.NotFoundError(msg='MCP 不存在')
        for mcp in mcps:
            self._validate_transport_permission(type=AIBuddyMcpType(mcp.type), is_superuser=is_superuser)
        return mcps

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        name: str | None,
        type: int | None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """
        获取 MCP 列表

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: MCP 名称
        :param type: MCP 类型
        :param is_superuser: 是否为超级管理员
        :return:
        """
        mcp_select = await ai_buddy_mcp_dao.get_select(
            user_id=None if is_superuser else user_id,
            name=name,
            type=type,
        )
        return await paging_data(db, mcp_select)

    async def create(
        self,
        *,
        db: AsyncSession,
        obj: CreateAIBuddyMcpParam,
        user_id: int,
        is_superuser: bool,
    ) -> None:
        """
        创建 MCP

        :param db: 数据库会话
        :param obj: 创建 MCP 参数
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        obj = self._normalize_transport_fields(obj=obj)
        self._validate_transport_permission(type=obj.type, is_superuser=is_superuser)
        if obj.tool_prefix and not match_string(r'^[A-Za-z0-9_-]+$', obj.tool_prefix):
            raise errors.RequestError(msg='MCP 工具名称前缀仅支持字母、数字、下划线和连字符')
        mcp = await ai_buddy_mcp_dao.get_by_name(db, name=obj.name, user_id=user_id)
        if mcp:
            raise errors.ConflictError(msg='MCP 已存在')
        await ai_buddy_mcp_dao.create(db, obj, user_id)

    async def import_json(
        self,
        *,
        db: AsyncSession,
        raw: str,
        user_id: int,
        is_superuser: bool,
    ) -> ImportAIBuddyMcpResult:
        """
        从标准 mcpServers JSON 导入 MCP

        :param db: 数据库会话
        :param raw: JSON 文本
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        items = parse_mcp_servers_json(raw, allow_stdio=is_superuser)
        created = 0
        skipped: list[str] = []
        for obj in items:
            existing = await ai_buddy_mcp_dao.get_by_name(db, name=obj.name, user_id=user_id)
            if existing:
                skipped.append(obj.name)
                continue
            await self.create(db=db, obj=obj, user_id=user_id, is_superuser=is_superuser)
            created += 1
        return ImportAIBuddyMcpResult(created=created, skipped=skipped)

    async def clone_mine(
        self,
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
        is_superuser: bool,
    ) -> None:
        """
        把可见的内置 MCP 复制成当前用户自己的副本，用于填写个人密钥

        :param db: 数据库会话
        :param pk: 源 MCP ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        source = await self.get(db=db, pk=pk, user_id=user_id)
        if source.user_id == user_id:
            raise errors.RequestError(msg='不能复制自己的 MCP')
        if await ai_buddy_mcp_dao.get_by_name(db, name=source.name, user_id=user_id):
            raise errors.ConflictError(msg='已有同名 MCP，请编辑自己的副本')
        await self.create(
            db=db,
            obj=CreateAIBuddyMcpParam(
                name=source.name,
                command=source.command,
                type=AIBuddyMcpType(source.type),
                description=source.description,
                url=source.url,
                headers=dict.fromkeys(source.headers, '') if source.headers else None,
                args=source.args,
                env=dict.fromkeys(source.env, '') if source.env else None,
                timeout=source.timeout,
                read_timeout=source.read_timeout,
                tool_prefix=source.tool_prefix,
                include_instructions=source.include_instructions,
            ),
            user_id=user_id,
            is_superuser=is_superuser,
        )

    async def update(
        self,
        *,
        db: AsyncSession,
        pk: int,
        obj: UpdateAIBuddyMcpParam,
        user_id: int,
        is_superuser: bool,
    ) -> int:
        """
        更新 MCP

        :param db: 数据库会话
        :param pk: MCP ID
        :param obj: 更新 MCP 参数
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        mcp = await ai_buddy_mcp_dao.get(db, pk, None if is_superuser else user_id)
        if not mcp:
            raise errors.NotFoundError(msg='MCP 不存在')
        if mcp.user_id == 0 and not is_superuser:
            raise errors.ForbiddenError(msg='不能修改内置 MCP')
        obj = obj.model_copy(
            update={
                'headers': restore_masked_sensitive_data(obj.headers, mcp.headers),
                'env': restore_masked_sensitive_data(obj.env, mcp.env),
            }
        )
        obj = self._normalize_transport_fields(obj=obj)
        self._validate_transport_permission(type=obj.type, is_superuser=is_superuser)
        if obj.tool_prefix and not match_string(r'^[A-Za-z0-9_-]+$', obj.tool_prefix):
            raise errors.RequestError(msg='MCP 工具名称前缀仅支持字母、数字、下划线和连字符')
        if mcp.name != obj.name and await ai_buddy_mcp_dao.get_by_name(db, name=obj.name, user_id=mcp.user_id):
            raise errors.ConflictError(msg='MCP 已存在')

        transport_changed = mcp.url != obj.url or mcp.type != obj.type
        count = await ai_buddy_mcp_dao.update(db, pk, obj, mcp.user_id)
        if count > 0 and transport_changed:
            await ai_buddy_mcp_oauth_config_dao.disable(db, pk, secrets.token_hex(16))
            await ai_buddy_mcp_oauth_dao.invalidate(db, pk, secrets.token_hex(16))
        return count

    @staticmethod
    async def delete(*, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False) -> int:
        """
        删除 MCP

        :param db: 数据库会话
        :param pk: MCP ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        mcp = await ai_buddy_mcp_dao.get(db, pk, None if is_superuser else user_id)
        if not mcp:
            raise errors.NotFoundError(msg='MCP 不存在')
        if mcp.user_id == 0 and not is_superuser:
            raise errors.ForbiddenError(msg='不能删除内置 MCP')

        count = await ai_buddy_mcp_dao.delete(db, pk, mcp.user_id)
        if count > 0:
            await ai_buddy_mcp_oauth_config_dao.disable(db, pk, secrets.token_hex(16))
            await ai_buddy_mcp_oauth_dao.invalidate(db, pk, secrets.token_hex(16))
        return count


ai_buddy_mcp_service: AIBuddyMcpService = AIBuddyMcpService()
