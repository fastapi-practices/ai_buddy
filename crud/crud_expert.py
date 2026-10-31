from collections.abc import Sequence

from sqlalchemy import Select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.expert import AIBuddyExpert
from backend.plugin.ai_buddy.schema.expert import CreateAIBuddyExpertParam, UpdateAIBuddyExpertParam
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID, visible_owner_ids
from backend.utils.timezone import timezone


class CRUDAIBuddyExpert(CRUDPlus[AIBuddyExpert]):
    """AI 专家模板数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyExpert | None:
        """
        获取专家模板

        :param db: 数据库会话
        :param pk: 专家 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_id_and_user_id(self, db: AsyncSession, pk: int, user_id: int) -> AIBuddyExpert | None:
        """
        获取当前用户可用的专家模板

        :param db: 数据库会话
        :param pk: 专家 ID
        :param user_id: 用户 ID
        :return:
        """
        expert = await self.select_model(db, pk, deleted=0)
        if expert is None or expert.user_id not in {user_id, SYSTEM_OWNER_USER_ID}:
            return None
        return expert

    async def get_by_name(self, db: AsyncSession, user_id: int, name: str) -> AIBuddyExpert | None:
        """
        通过名称获取当前用户专家模板

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 专家名称
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, name=name, deleted=0)

    async def get_select(self, user_id: int | None, name: str | None) -> Select:
        """
        获取专家模板列表查询表达式

        :param user_id: 用户 ID，空则不限制归属
        :param name: 专家名称
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if user_id is not None:
            filters['user_id__in'] = visible_owner_ids(user_id)
        if name is not None:
            filters['name__like'] = f'%{name}%'
        return await self.select_order(['sort', 'id'], ['desc', 'desc'], **filters)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyExpert]:
        """
        获取当前用户可用的所有专家模板

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(
            db,
            ['sort', 'id'],
            ['desc', 'desc'],
            user_id__in=[SYSTEM_OWNER_USER_ID, user_id],
            deleted=0,
        )

    async def create(self, db: AsyncSession, obj: CreateAIBuddyExpertParam, user_id: int) -> None:
        """
        创建专家模板

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        await self.create_model(db, obj, user_id=user_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyExpertParam) -> int:
        """
        更新专家模板

        :param db: 数据库会话
        :param pk: 专家 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def increment_usage(self, db: AsyncSession, pk: int) -> int:
        """
        累加专家使用次数

        :param db: 数据库会话
        :param pk: 专家 ID
        :return:
        """
        stmt = (
            update(self.model)
            .where(self.model.id == pk, self.model.deleted == 0)
            .values(usage_count=self.model.usage_count + 1)
        )
        result = await db.execute(stmt)
        return result.rowcount or 0

    async def delete(self, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除专家模板

        :param db: 数据库会话
        :param pk: 专家 ID
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


ai_buddy_expert_dao: CRUDAIBuddyExpert = CRUDAIBuddyExpert(AIBuddyExpert)
