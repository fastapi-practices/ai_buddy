from collections.abc import Sequence

from sqlalchemy import Select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.enums import AIBuddyAssistantCategory, AIBuddyAssistantSortType
from backend.plugin.ai_buddy.model.assistant import AIBuddyAssistant
from backend.plugin.ai_buddy.schema.assistant import CreateAIBuddyAssistantParam, UpdateAIBuddyAssistantParam
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID, visible_owner_ids
from backend.utils.timezone import timezone


def _assistant_sort_spec(sort_type: AIBuddyAssistantSortType) -> tuple[list[str], list[str]]:
    """
    解析助手列表排序列

    :param sort_type: 排序方式
    :return:
    """
    match sort_type:
        case AIBuddyAssistantSortType.hottest:
            return ['usage_count', 'id'], ['desc', 'desc']
        case AIBuddyAssistantSortType.newest:
            return ['id'], ['desc']
        case _:
            return ['sort', 'id'], ['desc', 'desc']


class CRUDAIBuddyAssistant(CRUDPlus[AIBuddyAssistant]):
    """AI 助手数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyAssistant | None:
        """
        获取 AI 助手

        :param db: 数据库会话
        :param pk: 助手 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_id_and_user_id(self, db: AsyncSession, pk: int, user_id: int) -> AIBuddyAssistant | None:
        """
        获取当前用户可用的助手

        :param db: 数据库会话
        :param pk: 助手 ID
        :param user_id: 用户 ID
        :return:
        """
        assistant = await self.select_model(db, pk, deleted=0)
        if assistant is None or assistant.user_id not in {user_id, SYSTEM_OWNER_USER_ID}:
            return None
        return assistant

    async def get_by_name(self, db: AsyncSession, user_id: int, name: str) -> AIBuddyAssistant | None:
        """
        通过名称获取当前用户助手

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 助手名称
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, name=name, deleted=0)

    async def get_select(
        self,
        user_id: int | None,
        name: str | None,
        category: AIBuddyAssistantCategory | None,
        sort_type: AIBuddyAssistantSortType = AIBuddyAssistantSortType.newest,
    ) -> Select:
        """
        获取助手列表查询表达式

        :param user_id: 用户 ID，空则不限制归属
        :param name: 助手名称
        :param category: 助手分类编码
        :param sort_type: 排序方式
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if user_id is not None:
            filters['user_id__in'] = visible_owner_ids(user_id)
        if name is not None:
            filters['name__like'] = f'%{name}%'
        if category is not None:
            filters['category'] = category
        sort_columns, sort_orders = _assistant_sort_spec(sort_type)
        return await self.select_order(sort_columns, sort_orders, **filters)

    async def get_all(
        self,
        db: AsyncSession,
        user_id: int,
        sort_type: AIBuddyAssistantSortType = AIBuddyAssistantSortType.newest,
    ) -> Sequence[AIBuddyAssistant]:
        """
        获取当前用户可用的所有助手

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param sort_type: 排序方式
        :return:
        """
        sort_columns, sort_orders = _assistant_sort_spec(sort_type)
        return await self.select_models_order(
            db,
            sort_columns,
            sort_orders,
            user_id__in=[SYSTEM_OWNER_USER_ID, user_id],
            deleted=0,
        )

    async def create(self, db: AsyncSession, obj: CreateAIBuddyAssistantParam, user_id: int) -> None:
        """
        创建 AI 助手

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        await self.create_model(db, obj, user_id=user_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyAssistantParam) -> int:
        """
        更新 AI 助手

        :param db: 数据库会话
        :param pk: 助手 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def increment_usage(self, db: AsyncSession, pk: int) -> int:
        """
        累加助手使用次数

        :param db: 数据库会话
        :param pk: 助手 ID
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
        删除 AI 助手

        :param db: 数据库会话
        :param pk: 助手 ID
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


ai_buddy_assistant_dao: CRUDAIBuddyAssistant = CRUDAIBuddyAssistant(AIBuddyAssistant)
