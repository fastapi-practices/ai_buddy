from collections.abc import Sequence

import sqlalchemy as sa

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.workspace import AIBuddyWorkspace
from backend.plugin.ai_buddy.schema.workspace import (
    CreateAIBuddyWorkspaceParam,
    UpdateAIBuddyWorkspaceParam,
)
from backend.utils.timezone import timezone


class CRUDAIBuddyWorkspace(CRUDPlus[AIBuddyWorkspace]):
    """AI 工作区数据库操作类"""

    async def get(
        self, db: AsyncSession, user_id: int, workspace_id: str, *, for_update: bool = False
    ) -> AIBuddyWorkspace | None:
        """获取当前用户工作区"""
        statement = sa.select(self.model).where(
            self.model.user_id == user_id, self.model.workspace_id == workspace_id, self.model.deleted == 0
        )
        if for_update:
            statement = statement.with_for_update()
        return await db.scalar(statement)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyWorkspace]:
        """获取当前用户所有工作区"""
        return await self.select_models_order(db, 'id', 'desc', user_id=user_id, deleted=0)

    async def create(self, db: AsyncSession, user_id: int, obj: CreateAIBuddyWorkspaceParam) -> AIBuddyWorkspace:
        """创建工作区"""
        return await self.create_model(db, obj, user_id=user_id, flush=True)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyWorkspaceParam | dict) -> int:
        """更新工作区"""
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def update_if_revision(self, db: AsyncSession, pk: int, revision: int, obj: dict[str, object]) -> int:
        """按工作区版本条件原子更新并递增版本"""
        payload = {key: value for key, value in obj.items() if key != 'revision'}
        payload['revision'] = self.model.revision + 1
        result = await db.execute(
            sa
            .update(self.model)
            .where(self.model.id == pk, self.model.revision == revision, self.model.deleted == 0)
            .values(**payload)
        )
        return result.rowcount or 0

    async def delete(self, db: AsyncSession, user_id: int, workspace_id: str) -> int:
        """删除当前用户工作区"""
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            user_id=user_id,
            workspace_id=workspace_id,
            deleted=0,
        )


ai_buddy_workspace_dao: CRUDAIBuddyWorkspace = CRUDAIBuddyWorkspace(AIBuddyWorkspace)
