from collections.abc import Sequence

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.subagent import SYSTEM_SUBAGENT_USER_ID, AIBuddySubagent
from backend.plugin.ai_buddy.schema.subagent import CreateAIBuddySubagentParam, UpdateAIBuddySubagentParam
from backend.plugin.ai_buddy.utils.ownership import visible_owner_ids
from backend.utils.timezone import timezone


class CRUDAIBuddySubagent(CRUDPlus[AIBuddySubagent]):
    """AI 子代理数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddySubagent | None:
        """
        获取子代理

        :param db: 数据库会话
        :param pk: 子代理 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_id_and_user_id(self, db: AsyncSession, pk: int, user_id: int) -> AIBuddySubagent | None:
        """
        获取当前用户可用的子代理

        :param db: 数据库会话
        :param pk: 子代理 ID
        :param user_id: 用户 ID
        :return:
        """
        subagent = await self.select_model(db, pk, deleted=0)
        if subagent is None or subagent.user_id not in {user_id, SYSTEM_SUBAGENT_USER_ID}:
            return None
        return subagent

    async def get_by_name(self, db: AsyncSession, user_id: int, name: str) -> AIBuddySubagent | None:
        """
        通过名称获取当前用户子代理

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 子代理名称
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, name=name, deleted=0)

    async def get_select(self, user_id: int | None, name: str | None) -> Select:
        """
        获取子代理列表查询表达式

        :param user_id: 用户 ID，空则不限制归属
        :param name: 子代理名称
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if user_id is not None:
            filters['user_id__in'] = visible_owner_ids(user_id)
        if name is not None:
            filters['name__like'] = f'%{name}%'
        return await self.select_order(['sort', 'id'], ['asc', 'desc'], **filters)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddySubagent]:
        """
        获取当前用户可用的所有子代理

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(
            db,
            ['sort', 'id'],
            ['asc', 'desc'],
            user_id__in=[SYSTEM_SUBAGENT_USER_ID, user_id],
            deleted=0,
        )

    async def create(self, db: AsyncSession, obj: CreateAIBuddySubagentParam, user_id: int) -> None:
        """
        创建子代理

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        await self.create_model(db, obj, user_id=user_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddySubagentParam) -> int:
        """
        更新子代理

        :param db: 数据库会话
        :param pk: 子代理 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除子代理

        :param db: 数据库会话
        :param pk: 子代理 ID
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


ai_buddy_subagent_dao: CRUDAIBuddySubagent = CRUDAIBuddySubagent(AIBuddySubagent)
