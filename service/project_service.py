from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.crud.crud_project import ai_buddy_project_dao
from backend.plugin.ai_buddy.model import AIBuddyProject
from backend.plugin.ai_buddy.schema.project import (
    CreateAIBuddyProjectParam,
    UpdateAIBuddyProjectParam,
)


class AIBuddyProjectService:
    """AI 项目服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyProject]:
        """
        获取当前用户所有项目

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await ai_buddy_project_dao.get_all(db, user_id)

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int) -> AIBuddyProject:
        """
        获取项目

        :param db: 数据库会话
        :param pk: 项目 ID
        :param user_id: 用户 ID
        :return:
        """
        project = await ai_buddy_project_dao.get(db, pk)
        if not project or project.user_id != user_id:
            raise errors.NotFoundError(msg='项目不存在')
        return project

    @staticmethod
    async def create(*, db: AsyncSession, user_id: int, obj: CreateAIBuddyProjectParam) -> None:
        """
        创建项目

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param obj: 创建项目参数
        :return:
        """
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='项目名称不能为空')
        if await ai_buddy_project_dao.get_by_name(db, user_id, name):
            raise errors.ConflictError(msg='项目名称已存在')
        obj.name = name
        await ai_buddy_project_dao.create(db, user_id, obj)

    async def update(self, *, db: AsyncSession, pk: int, user_id: int, obj: UpdateAIBuddyProjectParam) -> int:
        """
        更新项目

        :param db: 数据库会话
        :param pk: 项目 ID
        :param user_id: 用户 ID
        :param obj: 更新项目参数
        :return:
        """
        await self.get(db=db, pk=pk, user_id=user_id)
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='项目名称不能为空')
        existed = await ai_buddy_project_dao.get_by_name(db, user_id, name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='项目名称已存在')
        obj.name = name
        return await ai_buddy_project_dao.update(db, pk, obj)

    async def delete(self, *, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除项目并清空会话归属

        :param db: 数据库会话
        :param pk: 项目 ID
        :param user_id: 用户 ID
        :return:
        """
        await self.get(db=db, pk=pk, user_id=user_id)
        await ai_buddy_conversation_dao.clear_project(db, pk)
        return await ai_buddy_project_dao.delete(db, pk)


ai_buddy_project_service: AIBuddyProjectService = AIBuddyProjectService()
