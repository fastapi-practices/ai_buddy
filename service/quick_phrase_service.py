from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.ai_buddy.crud.crud_quick_phrase import ai_buddy_quick_phrase_dao
from backend.plugin.ai_buddy.model.quick_phrase import AIBuddyQuickPhrase
from backend.plugin.ai_buddy.schema.quick_phrase import (
    CreateAIBuddyQuickPhraseParam,
    UpdateAIBuddyQuickPhraseParam,
)
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID


class AIBuddyQuickPhraseService:
    """AI 快捷短语服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyQuickPhrase]:
        """
        获取当前用户所有快捷短语

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await ai_buddy_quick_phrase_dao.get_all(db, user_id)

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False) -> AIBuddyQuickPhrase:
        """
        获取快捷短语详情

        :param db: 数据库会话
        :param pk: 快捷短语 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        if is_superuser:
            quick_phrase = await ai_buddy_quick_phrase_dao.get(db, pk)
        else:
            quick_phrase = await ai_buddy_quick_phrase_dao.get_by_id_and_user_id(db, pk, user_id)
        if not quick_phrase:
            raise errors.NotFoundError(msg='快捷短语不存在')
        return quick_phrase

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        content: str | None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """
        获取快捷短语列表

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param content: 短语内容
        :param is_superuser: 是否为超级管理员
        :return:
        """
        quick_phrase_select = await ai_buddy_quick_phrase_dao.get_select(None if is_superuser else user_id, content)
        return await paging_data(db, quick_phrase_select)

    @staticmethod
    async def create(*, db: AsyncSession, obj: CreateAIBuddyQuickPhraseParam, user_id: int) -> None:
        """
        创建快捷短语

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        title = obj.title.strip()
        if not title:
            raise errors.RequestError(msg='快捷短语标题不能为空')
        content = obj.content.strip()
        if not content:
            raise errors.RequestError(msg='快捷短语内容不能为空')
        await ai_buddy_quick_phrase_dao.create(
            db,
            obj.model_copy(update={'title': title, 'content': content}),
            user_id,
        )

    @staticmethod
    async def update(
        *,
        db: AsyncSession,
        pk: int,
        obj: UpdateAIBuddyQuickPhraseParam,
        user_id: int,
        is_superuser: bool = False,
    ) -> int:
        """
        更新快捷短语

        :param db: 数据库会话
        :param pk: 快捷短语 ID
        :param obj: 更新参数
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        if is_superuser:
            quick_phrase = await ai_buddy_quick_phrase_dao.get(db, pk)
        else:
            quick_phrase = await ai_buddy_quick_phrase_dao.get_by_id_and_user_id(db, pk, user_id)
        if not quick_phrase:
            raise errors.NotFoundError(msg='快捷短语不存在')
        if quick_phrase.user_id == SYSTEM_OWNER_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统内置快捷短语不允许修改')
        title = obj.title.strip()
        if not title:
            raise errors.RequestError(msg='快捷短语标题不能为空')
        content = obj.content.strip()
        if not content:
            raise errors.RequestError(msg='快捷短语内容不能为空')
        return await ai_buddy_quick_phrase_dao.update(
            db,
            pk,
            obj.model_copy(update={'title': title, 'content': content}),
        )

    @staticmethod
    async def delete(*, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False) -> int:
        """
        删除快捷短语

        :param db: 数据库会话
        :param pk: 快捷短语 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        if is_superuser:
            quick_phrase = await ai_buddy_quick_phrase_dao.get(db, pk)
        else:
            quick_phrase = await ai_buddy_quick_phrase_dao.get_by_id_and_user_id(db, pk, user_id)
        if not quick_phrase:
            raise errors.NotFoundError(msg='快捷短语不存在')
        if quick_phrase.user_id == SYSTEM_OWNER_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统内置快捷短语不允许删除')
        return await ai_buddy_quick_phrase_dao.delete(db, pk, quick_phrase.user_id)


ai_buddy_quick_phrase_service: AIBuddyQuickPhraseService = AIBuddyQuickPhraseService()
