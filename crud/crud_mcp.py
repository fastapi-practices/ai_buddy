from collections.abc import Sequence

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model import AIBuddyMcp
from backend.plugin.ai_buddy.schema.mcp import CreateAIBuddyMcpParam, UpdateAIBuddyMcpParam
from backend.plugin.ai_buddy.utils.ownership import visible_owner_ids
from backend.utils.timezone import timezone


class CRUDAIBuddyMcp(CRUDPlus[AIBuddyMcp]):
    """AI MCP 数据库操作类"""

    async def get(self, db: AsyncSession, pk: int, user_id: int | None = None) -> AIBuddyMcp | None:
        """
        获取 MCP

        :param db: 数据库会话
        :param pk: MCP ID
        :param user_id: 用户 ID，空则不限制归属
        :return:
        """
        mcp = await self.select_model(db, pk, deleted=0)
        if mcp is None:
            return None
        if user_id is not None and mcp.user_id not in set(visible_owner_ids(user_id)):
            return None
        return mcp

    async def get_by_ids(self, db: AsyncSession, pks: list[int], user_id: int) -> Sequence[AIBuddyMcp]:
        """
        获取指定 MCP 列表，包含当前用户与预设

        :param db: 数据库会话
        :param pks: MCP ID 列表
        :param user_id: 用户 ID
        :return:
        """
        mcps = await self.select_models(db, id__in=pks, deleted=0)
        return [mcp for mcp in mcps if mcp.user_id in set(visible_owner_ids(user_id))]

    async def get_by_name(self, db: AsyncSession, name: str, user_id: int) -> AIBuddyMcp | None:
        """
        通过名称获取 MCP

        :param db: 数据库会话
        :param name: MCP 名称
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_model_by_column(db, name=name, user_id=user_id, deleted=0)

    async def get_select(self, user_id: int | None, name: str | None, type: int | None) -> Select:
        """
        获取 MCP 列表查询表达式

        :param user_id: 用户 ID，空则不限制归属
        :param name: MCP 名称
        :param type: MCP 类型
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if user_id is not None:
            filters['user_id__in'] = visible_owner_ids(user_id)
        if name is not None:
            filters.update(name__like=f'%{name}%')
        if type is not None:
            filters.update(type=type)
        return await self.select_order('id', 'desc', **filters)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyMcp]:
        """
        获取所有 MCP，包含当前用户与预设

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(db, 'id', 'desc', user_id__in=[0, user_id], deleted=0)

    async def create(self, db: AsyncSession, obj: CreateAIBuddyMcpParam, user_id: int) -> None:
        """
        创建 MCP

        :param db: 数据库会话
        :param obj: 创建 MCP 参数
        :param user_id: 用户 ID
        :return:
        """
        await self.create_model(db, obj, user_id=user_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyMcpParam, user_id: int) -> int:
        """
        更新 MCP

        :param db: 数据库会话
        :param pk: MCP ID
        :param obj: 更新 MCP 参数
        :param user_id: 用户 ID
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, user_id=user_id, deleted=0)

    async def delete(self, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除 MCP

        :param db: 数据库会话
        :param pk: MCP ID
        :param user_id: 用户 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id=pk,
            user_id=user_id,
            deleted=0,
        )


ai_buddy_mcp_dao: CRUDAIBuddyMcp = CRUDAIBuddyMcp(AIBuddyMcp)
