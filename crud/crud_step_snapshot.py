from collections.abc import Collection

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.step_snapshot import AIBuddyStepSnapshot


class CRUDAIBuddyStepSnapshot(CRUDPlus[AIBuddyStepSnapshot]):
    """AI 步骤快照数据库操作类"""

    async def get_by_key(self, db: AsyncSession, run_id: str, idempotency_key: str) -> AIBuddyStepSnapshot | None:
        """
        通过边界幂等键获取快照

        :param db: 数据库会话
        :param run_id: 运行 ID
        :param idempotency_key: 边界幂等键
        :return:
        """
        return await self.select_model_by_column(db, run_id=run_id, idempotency_key=idempotency_key)

    async def get_latest(
        self, db: AsyncSession, run_id: str, *, include_interrupted: bool
    ) -> AIBuddyStepSnapshot | None:
        """
        获取运行最新快照，默认只返回已结算的快照

        :param db: 数据库会话
        :param run_id: 运行 ID
        :param include_interrupted: 是否包含中断快照
        :return:
        """
        stmt = select(self.model).where(self.model.run_id == run_id)
        if not include_interrupted:
            stmt = stmt.where(self.model.state == 'complete')
        return (await db.execute(stmt.order_by(self.model.id.desc()).limit(1))).scalar_one_or_none()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyStepSnapshot) -> None:
        """
        保存快照

        :param db: 数据库会话
        :param obj: 快照
        :return:
        """
        db.add(obj)
        await db.flush()

    @staticmethod
    async def delete_by_run_ids(db: AsyncSession, run_ids: Collection[str]) -> int:
        """
        物理删除指定运行的记录

        :param db: 数据库会话
        :param run_ids: 运行 ID 集合
        :return:
        """
        if not run_ids:
            return 0
        stmt = delete(AIBuddyStepSnapshot).where(AIBuddyStepSnapshot.run_id.in_(run_ids))
        return (await db.execute(stmt)).rowcount


ai_buddy_step_snapshot_dao: CRUDAIBuddyStepSnapshot = CRUDAIBuddyStepSnapshot(AIBuddyStepSnapshot)
