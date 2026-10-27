from collections.abc import Sequence

import sqlalchemy as sa

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.workspace_file import AIBuddyWorkspaceFile
from backend.plugin.ai_buddy.schema.workspace_file import (
    CreateAIBuddyWorkspaceFileParam,
    UpsertAIBuddyWorkspaceFileParam,
)


class CRUDAIBuddyWorkspaceFile(CRUDPlus[AIBuddyWorkspaceFile]):
    """AI 工作区文件清单数据库操作类"""

    async def get(
        self,
        db: AsyncSession,
        user_id: int,
        workspace_id: str,
        relative_path: str,
    ) -> AIBuddyWorkspaceFile | None:
        """
        获取工作区文件清单

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param workspace_id: 工作区 ID
        :param relative_path: 相对路径
        :return:
        """
        return await self.select_model_by_column(
            db,
            user_id=user_id,
            workspace_id=workspace_id,
            relative_path=relative_path,
            deleted=0,
        )

    async def get_all(self, db: AsyncSession, user_id: int, workspace_id: str) -> Sequence[AIBuddyWorkspaceFile]:
        """
        获取工作区全部文件清单

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param workspace_id: 工作区 ID
        :return:
        """
        return await self.select_models_order(
            db,
            'relative_path',
            'asc',
            user_id=user_id,
            workspace_id=workspace_id,
            deleted=0,
        )

    async def create(
        self,
        db: AsyncSession,
        user_id: int,
        workspace_id: str,
        obj: CreateAIBuddyWorkspaceFileParam | UpsertAIBuddyWorkspaceFileParam,
    ) -> AIBuddyWorkspaceFile:
        """
        创建工作区文件清单

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param workspace_id: 工作区 ID
        :param obj: 创建工作区文件参数
        :return:
        """
        return await self.create_model(db, obj, user_id=user_id, workspace_id=workspace_id, flush=True)

    async def update(self, db: AsyncSession, pk: int, obj: dict) -> int:
        """
        更新工作区文件清单

        :param db: 数据库会话
        :param pk: 记录 ID
        :param obj: 工作区文件更新字段
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def update_if_revision(self, db: AsyncSession, pk: int, revision: int, obj: dict) -> int:
        """
        按文件版本条件更新工作区文件清单

        :param db: 数据库会话
        :param pk: 记录 ID
        :param revision: 版本号
        :param obj: 工作区文件更新字段
        :return:
        """
        result = await db.execute(
            sa
            .update(self.model)
            .where(self.model.id == pk, self.model.revision == revision, self.model.deleted == 0)
            .values(**obj)
        )
        return result.rowcount or 0


ai_buddy_workspace_file_dao: CRUDAIBuddyWorkspaceFile = CRUDAIBuddyWorkspaceFile(AIBuddyWorkspaceFile)
