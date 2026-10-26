from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.ai_buddy.crud.crud_assistant import ai_buddy_assistant_dao
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.enums import AIBuddyAssistantCategory, AIBuddyAssistantSortType
from backend.plugin.ai_buddy.model.assistant import SYSTEM_ASSISTANT_USER_ID, AIBuddyAssistant
from backend.plugin.ai_buddy.schema.assistant import CreateAIBuddyAssistantParam, UpdateAIBuddyAssistantParam


class AIBuddyAssistantService:
    """AI 助手服务类"""

    @staticmethod
    async def get_all(
        *,
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
        return await ai_buddy_assistant_dao.get_all(db, user_id, sort_type)

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False) -> AIBuddyAssistant:
        """
        获取助手详情

        :param db: 数据库会话
        :param pk: 助手 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        if is_superuser:
            assistant = await ai_buddy_assistant_dao.get(db, pk)
        else:
            assistant = await ai_buddy_assistant_dao.get_by_id_and_user_id(db, pk, user_id)
        if not assistant:
            raise errors.NotFoundError(msg='助手不存在')
        return assistant

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        name: str | None,
        category: AIBuddyAssistantCategory | None,
        sort_type: AIBuddyAssistantSortType = AIBuddyAssistantSortType.newest,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """
        获取助手列表

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 助手名称
        :param category: 助手分类编码
        :param sort_type: 排序方式
        :param is_superuser: 是否为超级管理员
        :return:
        """
        assistant_select = await ai_buddy_assistant_dao.get_select(
            None if is_superuser else user_id,
            name,
            category,
            sort_type,
        )
        return await paging_data(db, assistant_select)

    @staticmethod
    async def record_usage(*, db: AsyncSession, pk: int | None) -> None:
        """
        记录一次助手使用

        :param db: 数据库会话
        :param pk: 助手 ID
        :return:
        """
        if pk is None:
            return
        await ai_buddy_assistant_dao.increment_usage(db, pk)

    async def create(self, *, db: AsyncSession, obj: CreateAIBuddyAssistantParam, user_id: int) -> None:
        """
        创建助手

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        obj = self._normalize(obj=obj)
        if await ai_buddy_assistant_dao.get_by_name(db, user_id, obj.name):
            raise errors.ConflictError(msg='助手名称已存在')
        await ai_buddy_assistant_dao.create(db, obj, user_id)

    async def update(
        self,
        *,
        db: AsyncSession,
        pk: int,
        obj: UpdateAIBuddyAssistantParam,
        user_id: int,
        is_superuser: bool,
    ) -> int:
        """
        更新助手

        :param db: 数据库会话
        :param pk: 助手 ID
        :param obj: 更新参数
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        assistant = await self.get(db=db, pk=pk, user_id=user_id, is_superuser=is_superuser)
        if assistant.user_id == SYSTEM_ASSISTANT_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统默认助手不允许修改')
        obj = self._normalize(obj=obj)
        existed = await ai_buddy_assistant_dao.get_by_name(db, assistant.user_id, obj.name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='助手名称已存在')
        return await ai_buddy_assistant_dao.update(db, pk, obj)

    async def delete(self, *, db: AsyncSession, pk: int, user_id: int, is_superuser: bool) -> int:
        """
        删除助手并清空会话绑定

        :param db: 数据库会话
        :param pk: 助手 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        assistant = await self.get(db=db, pk=pk, user_id=user_id, is_superuser=is_superuser)
        if assistant.user_id == SYSTEM_ASSISTANT_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统默认助手不允许删除')
        await ai_buddy_conversation_dao.clear_assistant(db, pk)
        return await ai_buddy_assistant_dao.delete(db, pk, assistant.user_id)

    @staticmethod
    def _normalize(
        *, obj: CreateAIBuddyAssistantParam | UpdateAIBuddyAssistantParam
    ) -> CreateAIBuddyAssistantParam | UpdateAIBuddyAssistantParam:
        """
        规范化助手字段

        :param obj: 创建或更新参数
        :return:
        """
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='助手名称不能为空')
        prompt = obj.prompt.strip()
        if not prompt:
            raise errors.RequestError(msg='助手提示词不能为空')
        description = obj.description.strip() if obj.description else None
        category = obj.category
        starters: list[str] = []
        for item in obj.starters:
            text = item.strip()
            if text:
                starters.append(text)
        return obj.model_copy(
            update={
                'name': name,
                'prompt': prompt,
                'description': description or None,
                'category': category or None,
                'starters': starters,
            }
        )


ai_buddy_assistant_service: AIBuddyAssistantService = AIBuddyAssistantService()
