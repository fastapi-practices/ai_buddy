from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model import AIBuddyProject
from backend.plugin.ai_buddy.schema.project import CreateAIBuddyProjectParam, UpdateAIBuddyProjectParam
from backend.utils.timezone import timezone


class CRUDAIBuddyProject(CRUDPlus[AIBuddyProject]):
    """AI 项目数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyProject | None:
        """
        获取项目

        :param db: 数据库会话
        :param pk: 项目 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_name(self, db: AsyncSession, user_id: int, name: str) -> AIBuddyProject | None:
        """
        通过名称获取当前用户项目

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 项目名称
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, name=name, deleted=0)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyProject]:
        """
        获取当前用户所有项目

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(db, 'sort', 'asc', user_id=user_id, deleted=0)

    async def create(self, db: AsyncSession, user_id: int, obj: CreateAIBuddyProjectParam) -> None:
        """
        创建项目

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param obj: 创建项目参数
        :return:
        """
        await self.create_model(db, obj, user_id=user_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyProjectParam) -> int:
        """
        更新项目

        :param db: 数据库会话
        :param pk: 项目 ID
        :param obj: 更新项目参数
        :return:
        """
        return await self.update_model_by_column(db, obj.model_dump(exclude_unset=True), id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int) -> int:
        """
        删除项目

        :param db: 数据库会话
        :param pk: 项目 ID
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


ai_buddy_project_dao: CRUDAIBuddyProject = CRUDAIBuddyProject(AIBuddyProject)
