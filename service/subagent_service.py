from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.common.pagination import paging_data
from backend.plugin.ai_buddy.crud.crud_subagent import ai_buddy_subagent_dao
from backend.plugin.ai_buddy.model.subagent import SYSTEM_SUBAGENT_USER_ID, AIBuddySubagent
from backend.plugin.ai_buddy.schema.subagent import CreateAIBuddySubagentParam, UpdateAIBuddySubagentParam


class AIBuddySubagentService:
    """AI 子代理服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddySubagent]:
        """
        获取当前用户可用的所有子代理

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await ai_buddy_subagent_dao.get_all(db, user_id)

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int, is_superuser: bool = False) -> AIBuddySubagent:
        """
        获取子代理详情

        :param db: 数据库会话
        :param pk: 子代理 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        if is_superuser:
            subagent = await ai_buddy_subagent_dao.get(db, pk)
        else:
            subagent = await ai_buddy_subagent_dao.get_by_id_and_user_id(db, pk, user_id)
        if not subagent:
            raise errors.NotFoundError(msg='子代理不存在')
        return subagent

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        name: str | None,
        is_superuser: bool = False,
    ) -> dict[str, Any]:
        """
        获取子代理列表

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 子代理名称
        :param is_superuser: 是否为超级管理员
        :return:
        """
        subagent_select = await ai_buddy_subagent_dao.get_select(None if is_superuser else user_id, name)
        return await paging_data(db, subagent_select)

    async def create(self, *, db: AsyncSession, obj: CreateAIBuddySubagentParam, user_id: int) -> None:
        """
        创建子代理

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        obj = self._normalize(obj=obj)
        if await ai_buddy_subagent_dao.get_by_name(db, user_id, obj.name):
            raise errors.ConflictError(msg='子代理名称已存在')
        await ai_buddy_subagent_dao.create(db, obj, user_id)

    async def update(
        self,
        *,
        db: AsyncSession,
        pk: int,
        obj: UpdateAIBuddySubagentParam,
        user_id: int,
        is_superuser: bool,
    ) -> int:
        """
        更新子代理

        :param db: 数据库会话
        :param pk: 子代理 ID
        :param obj: 更新参数
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        subagent = await self.get(db=db, pk=pk, user_id=user_id, is_superuser=is_superuser)
        if subagent.user_id == SYSTEM_SUBAGENT_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统子代理不允许修改')
        obj = self._normalize(obj=obj)
        existed = await ai_buddy_subagent_dao.get_by_name(db, subagent.user_id, obj.name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='子代理名称已存在')
        return await ai_buddy_subagent_dao.update(db, pk, obj)

    async def delete(self, *, db: AsyncSession, pk: int, user_id: int, is_superuser: bool) -> int:
        """
        删除子代理

        :param db: 数据库会话
        :param pk: 子代理 ID
        :param user_id: 用户 ID
        :param is_superuser: 是否为超级管理员
        :return:
        """
        subagent = await self.get(db=db, pk=pk, user_id=user_id, is_superuser=is_superuser)
        if subagent.user_id == SYSTEM_SUBAGENT_USER_ID and not is_superuser:
            raise errors.ForbiddenError(msg='系统子代理不允许删除')
        return await ai_buddy_subagent_dao.delete(db, pk, subagent.user_id)

    @staticmethod
    def _normalize(
        *, obj: CreateAIBuddySubagentParam | UpdateAIBuddySubagentParam
    ) -> CreateAIBuddySubagentParam | UpdateAIBuddySubagentParam:
        """
        规范化子代理字段

        :param obj: 创建或更新参数
        :return:
        """
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='子代理名称不能为空')
        description = obj.description.strip()
        if not description:
            raise errors.RequestError(msg='子代理描述不能为空')
        prompt = obj.prompt.strip()
        if not prompt:
            raise errors.RequestError(msg='子代理提示词不能为空')
        return obj.model_copy(update={'name': name, 'description': description, 'prompt': prompt})


ai_buddy_subagent_service: AIBuddySubagentService = AIBuddySubagentService()
