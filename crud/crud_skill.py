from collections.abc import Sequence

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.skill import AIBuddySkill
from backend.plugin.ai_buddy.schema.skill import CreateAIBuddySkillParam
from backend.plugin.ai_buddy.utils.ownership import visible_owner_ids
from backend.utils.timezone import timezone


class CRUDAIBuddySkill(CRUDPlus[AIBuddySkill]):
    """AI 技能数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddySkill | None:
        """
        获取技能

        :param db: 数据库会话
        :param pk: 技能 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_id_and_user_id(self, db: AsyncSession, pk: int, user_id: int) -> AIBuddySkill | None:
        """
        获取当前用户可用的技能

        :param db: 数据库会话
        :param pk: 技能 ID
        :param user_id: 用户 ID
        :return:
        """
        skill = await self.select_model(db, pk, deleted=0)
        if skill is None or skill.user_id not in set(visible_owner_ids(user_id)):
            return None
        return skill

    async def get_by_name(self, db: AsyncSession, user_id: int, name: str) -> AIBuddySkill | None:
        """
        通过名称获取当前用户技能

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 技能名称
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, name=name, deleted=0)

    async def get_by_ids(self, db: AsyncSession, pks: list[int], user_id: int) -> Sequence[AIBuddySkill]:
        """
        获取当前用户可见的指定技能列表

        :param db: 数据库会话
        :param pks: 技能 ID 列表
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models(db, id__in=pks, user_id__in=visible_owner_ids(user_id), deleted=0)

    async def get_select(self, user_id: int | None, name: str | None) -> Select:
        """
        获取技能列表查询表达式

        :param user_id: 用户 ID，空则不限制归属
        :param name: 技能名称
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if user_id is not None:
            filters['user_id__in'] = visible_owner_ids(user_id)
        if name is not None:
            filters['name__like'] = f'%{name}%'
        return await self.select_order('id', 'desc', **filters)

    async def search(self, db: AsyncSession, user_id: int, query: str) -> Sequence[AIBuddySkill]:
        """
        按名称或描述搜索当前用户可见的技能

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param query: 搜索词
        :return:
        """
        needle = f'%{query.strip()}%'
        return await self.select_models_order(
            db,
            'id',
            'desc',
            or_(
                AIBuddySkill.name.ilike(needle),
                AIBuddySkill.description.ilike(needle),
            ),
            user_id__in=visible_owner_ids(user_id),
            deleted=0,
        )

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddySkill]:
        """
        获取当前用户可用的所有技能

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(
            db,
            'id',
            'desc',
            user_id__in=visible_owner_ids(user_id),
            deleted=0,
        )

    async def create(self, db: AsyncSession, user_id: int, obj: CreateAIBuddySkillParam) -> AIBuddySkill:
        """
        创建技能

        :param db: 数据库会话
        :param user_id: 上传用户 ID
        :param obj: 创建技能参数
        :return:
        """
        return await self.create_model(db, obj, user_id=user_id, flush=True)

    async def delete(self, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除技能

        :param db: 数据库会话
        :param pk: 技能 ID
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

    async def get_with_objects(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddySkill]:
        """
        获取当前用户已写入对象存储的记录，供历史数据补登记统一对象

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        stmt = select(self.model).where(
            self.model.user_id == user_id, self.model.deleted == 0, self.model.object_key.is_not(None)
        )
        return (await db.execute(stmt.order_by(self.model.id.asc()))).scalars().all()


ai_buddy_skill_dao: CRUDAIBuddySkill = CRUDAIBuddySkill(AIBuddySkill)
