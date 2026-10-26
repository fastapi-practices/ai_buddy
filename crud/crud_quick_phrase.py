from collections.abc import Sequence

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.quick_phrase import AIBuddyQuickPhrase
from backend.plugin.ai_buddy.schema.quick_phrase import CreateAIBuddyQuickPhraseParam, UpdateAIBuddyQuickPhraseParam
from backend.plugin.ai_buddy.utils.ownership import visible_owner_ids
from backend.utils.timezone import timezone


class CRUDAIBuddyQuickPhrase(CRUDPlus[AIBuddyQuickPhrase]):
    """AI 快捷短语数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyQuickPhrase | None:
        """
        获取 AI 快捷短语

        :param db: 数据库会话
        :param pk: 快捷短语 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_id_and_user_id(self, db: AsyncSession, pk: int, user_id: int) -> AIBuddyQuickPhrase | None:
        """
        获取当前用户的快捷短语

        :param db: 数据库会话
        :param pk: 快捷短语 ID
        :param user_id: 用户 ID
        :return:
        """
        phrase = await self.select_model(db, pk, deleted=0)
        if phrase is None or phrase.user_id not in set(visible_owner_ids(user_id)):
            return None
        return phrase

    async def get_select(self, user_id: int | None, content: str | None) -> Select:
        """
        获取快捷短语列表查询表达式

        :param user_id: 用户 ID，空则不限制归属
        :param content: 短语内容
        :return:
        """
        filters: dict[str, object] = {'deleted': 0}
        if user_id is not None:
            filters['user_id__in'] = visible_owner_ids(user_id)
        if content is not None:
            filters['content__like'] = f'%{content}%'
        return await self.select_order(['sort', 'id'], ['desc', 'desc'], **filters)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyQuickPhrase]:
        """
        获取当前用户的所有快捷短语

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(
            db,
            ['sort', 'id'],
            ['desc', 'desc'],
            user_id__in=visible_owner_ids(user_id),
            deleted=0,
        )

    async def create(self, db: AsyncSession, obj: CreateAIBuddyQuickPhraseParam, user_id: int) -> None:
        """
        创建 AI 快捷短语

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        await self.create_model(db, obj, user_id=user_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyQuickPhraseParam) -> int:
        """
        更新 AI 快捷短语

        :param db: 数据库会话
        :param pk: 快捷短语 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除 AI 快捷短语

        :param db: 数据库会话
        :param pk: 快捷短语 ID
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


ai_buddy_quick_phrase_dao: CRUDAIBuddyQuickPhrase = CRUDAIBuddyQuickPhrase(AIBuddyQuickPhrase)
