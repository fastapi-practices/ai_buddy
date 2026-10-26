from collections.abc import Generator, Sequence
from contextlib import contextmanager

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus
from starlette_context import context, request_cycle_context

from backend.common.exception import errors
from backend.plugin.ai_buddy.crud.crud_knowledge_base import ai_buddy_knowledge_base_dao
from backend.plugin.ai_buddy.model import AIBuddyKnowledge, AIBuddyKnowledgeBase
from backend.plugin.ai_buddy.schema.knowledge import CreateAIBuddyKnowledgeParam
from backend.plugin.ai_buddy.utils.ownership import visible_owner_ids
from backend.utils.timezone import timezone


@contextmanager
def knowledge_visibility_context(*, user_id: int, is_superuser: bool = False) -> Generator[None, None, None]:
    """
    为知识可见性查询提供显式用户上下文

    :param user_id: 当前用户 ID
    :param is_superuser: 是否为后台超级管理员
    :return:
    """
    if type(user_id) is not int or user_id < 0:
        raise errors.AuthorizationError(msg='知识访问缺少用户上下文')
    user_context = dict(context.data) if context.exists() else {}
    user_context.update(user_id=user_id, is_superuser=is_superuser)
    with request_cycle_context(user_context):
        yield


class CRUDAIBuddyKnowledge(CRUDPlus[AIBuddyKnowledge]):
    """AI 知识数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyKnowledge | None:
        """
        获取知识，不限制归属，供内部管理及写入校验使用

        :param db: 数据库会话
        :param pk: 知识 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_select(self, title: str | None, knowledge_base_id: int | None = None) -> Select:
        """
        获取知识文档查询表达式，不限制归属，供内部管理使用

        :param title: 知识标题
        :param knowledge_base_id: 知识库 ID
        :return:
        """
        filters = {'deleted': 0}
        if title is not None:
            filters['title__like'] = f'%{title}%'
        if knowledge_base_id is not None:
            filters['knowledge_base_id'] = knowledge_base_id
        return await self.select_order('id', 'desc', **filters)

    async def get_all(
        self,
        db: AsyncSession,
        knowledge_base_id: int | None = None,
        *,
        default_only: bool = False,
    ) -> Sequence[AIBuddyKnowledge]:
        """
        获取知识文档，不限制归属，供索引重建及内部删除使用

        :param db: 数据库会话
        :param knowledge_base_id: 知识库 ID
        :param default_only: 是否仅查询继承全局向量配置的知识库文档
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if knowledge_base_id is not None:
            filters['knowledge_base_id'] = knowledge_base_id
        if not default_only:
            return await self.select_models_order(db, 'id', 'desc', **filters)
        statement = await self.select_order('id', 'desc', **filters)
        statement = statement.join(AIBuddyKnowledgeBase, self.model.knowledge_base_id == AIBuddyKnowledgeBase.id).where(
            AIBuddyKnowledgeBase.deleted == 0,
            AIBuddyKnowledgeBase.provider_id.is_(None),
            AIBuddyKnowledgeBase.model_id.is_(None),
        )
        return (await db.scalars(statement)).all()

    async def get_visible_select(
        self,
        db: AsyncSession,
        title: str | None = None,
        knowledge_base_id: int | None = None,
        *,
        user_id: int,
        is_superuser: bool = False,
    ) -> Select:
        """
        获取同时满足文档归属及知识库可见性的查询表达式

        :param db: 数据库会话
        :param title: 知识标题
        :param knowledge_base_id: 知识库 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为后台超级管理员
        :return:
        """
        with knowledge_visibility_context(user_id=user_id, is_superuser=is_superuser):
            base_select = await ai_buddy_knowledge_base_dao.get_select(None if is_superuser else user_id, None)
            if knowledge_base_id is not None:
                base_select = base_select.where(ai_buddy_knowledge_base_dao.model.id == knowledge_base_id)
            bases = (await db.scalars(base_select)).all()
        statement = await self.get_select(title, knowledge_base_id)
        statement = statement.where(self.model.knowledge_base_id.in_([base.id for base in bases]))
        if not is_superuser:
            statement = statement.where(self.model.user_id.in_(visible_owner_ids(user_id)))
        return statement

    async def get_visible(
        self,
        db: AsyncSession,
        pk: int,
        *,
        user_id: int,
        is_superuser: bool = False,
    ) -> AIBuddyKnowledge | None:
        """
        获取当前用户可见知识

        :param db: 数据库会话
        :param pk: 知识 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为后台超级管理员
        :return:
        """
        statement = await self.get_visible_select(db, user_id=user_id, is_superuser=is_superuser)
        return await db.scalar(statement.where(self.model.id == pk).execution_options(populate_existing=True))

    async def get_all_visible(
        self,
        db: AsyncSession,
        knowledge_base_id: int | None = None,
        *,
        user_id: int,
        is_superuser: bool = False,
    ) -> Sequence[AIBuddyKnowledge]:
        """
        获取当前用户可见知识文档

        :param db: 数据库会话
        :param knowledge_base_id: 知识库 ID
        :param user_id: 当前用户 ID
        :param is_superuser: 是否为后台超级管理员
        :return:
        """
        statement = await self.get_visible_select(
            db,
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            is_superuser=is_superuser,
        )
        return (await db.scalars(statement.execution_options(populate_existing=True))).all()

    async def create(self, db: AsyncSession, user_id: int, obj: CreateAIBuddyKnowledgeParam) -> AIBuddyKnowledge:
        """
        创建知识

        :param db: 数据库会话
        :param user_id: 上传用户 ID
        :param obj: 创建知识参数
        :return:
        """
        return await self.create_model(db, obj, user_id=user_id, flush=True)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        删除知识

        :param db: 数据库会话
        :param pk: 知识 ID
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

    async def get_with_objects(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyKnowledge]:
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


ai_buddy_knowledge_dao: CRUDAIBuddyKnowledge = CRUDAIBuddyKnowledge(AIBuddyKnowledge)
