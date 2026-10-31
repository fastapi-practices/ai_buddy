from collections.abc import Sequence

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.knowledge_base import AIBuddyKnowledgeBase
from backend.plugin.ai_buddy.schema.knowledge_base import (
    CreateAIBuddyKnowledgeBaseParam,
    UpdateAIBuddyKnowledgeBaseParam,
)
from backend.plugin.ai_buddy.utils.ownership import visible_owner_ids
from backend.utils.timezone import timezone


class CRUDAIBuddyKnowledgeBase(CRUDPlus[AIBuddyKnowledgeBase]):
    """AI 知识库数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyKnowledgeBase | None:
        """
        获取知识库

        :param db: 数据库会话
        :param pk: 知识库 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_visible(
        self, db: AsyncSession, pk: int, *, user_id: int, is_superuser: bool = False
    ) -> AIBuddyKnowledgeBase | None:
        """
        获取当前用户可见的知识库

        :param db: 数据库会话
        :param pk: 知识库 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为后台超级管理员
        :return:
        """
        knowledge_base = await self.get(db, pk)
        if knowledge_base is None or (not is_superuser and knowledge_base.user_id not in visible_owner_ids(user_id)):
            return None
        return knowledge_base

    async def get_by_name(self, db: AsyncSession, user_id: int, name: str) -> AIBuddyKnowledgeBase | None:
        """
        通过名称获取当前用户知识库

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 知识库名称
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, name=name, deleted=0)

    async def get_by_ids(self, db: AsyncSession, pks: list[int], user_id: int) -> Sequence[AIBuddyKnowledgeBase]:
        """
        获取当前用户可见的指定知识库列表

        :param db: 数据库会话
        :param pks: 知识库 ID 列表
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models(db, id__in=pks, user_id__in=visible_owner_ids(user_id), deleted=0)

    async def get_select(self, user_id: int | None, name: str | None) -> Select:
        """
        获取知识库列表查询表达式

        :param user_id: 用户 ID，空则不限制归属
        :param name: 知识库名称
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if user_id is not None:
            filters['user_id__in'] = visible_owner_ids(user_id)
        if name is not None:
            filters['name__like'] = f'%{name}%'
        return await self.select_order('id', 'desc', **filters)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyKnowledgeBase]:
        """
        获取当前用户所有知识库

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

    async def get_all_owned(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyKnowledgeBase]:
        """
        获取当前用户自己创建的知识库

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(db, 'id', 'desc', user_id=user_id, deleted=0)

    async def create(
        self,
        db: AsyncSession,
        user_id: int,
        obj: CreateAIBuddyKnowledgeBaseParam,
    ) -> AIBuddyKnowledgeBase:
        """
        创建知识库

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param obj: 创建参数
        :return:
        """
        return await self.create_model(db, obj, user_id=user_id, flush=True)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyKnowledgeBaseParam) -> int:
        """
        更新知识库

        :param db: 数据库会话
        :param pk: 知识库 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        删除知识库

        :param db: 数据库会话
        :param pk: 知识库 ID
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
            deleted=0,
        )


ai_buddy_knowledge_base_dao: CRUDAIBuddyKnowledgeBase = CRUDAIBuddyKnowledgeBase(AIBuddyKnowledgeBase)
