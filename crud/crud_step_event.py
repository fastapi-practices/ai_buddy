from collections.abc import Collection, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.step_event import AIBuddyStepEvent


class CRUDAIBuddyStepEvent(CRUDPlus[AIBuddyStepEvent]):
    """AI 步骤事件数据库操作类"""

    async def get_by_key(self, db: AsyncSession, run_id: str, idempotency_key: str) -> AIBuddyStepEvent | None:
        """
        通过边界幂等键获取事件

        :param db: 数据库会话
        :param run_id: 运行 ID
        :param idempotency_key: 边界幂等键
        :return:
        """
        return await self.select_model_by_column(db, run_id=run_id, idempotency_key=idempotency_key)

    async def get_all(self, db: AsyncSession, run_id: str) -> Sequence[AIBuddyStepEvent]:
        """
        按写入顺序获取运行事件

        :param db: 数据库会话
        :param run_id: 运行 ID
        :return:
        """
        stmt = select(self.model).where(self.model.run_id == run_id).order_by(self.model.id.asc())
        return (await db.execute(stmt)).scalars().all()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyStepEvent) -> None:
        """
        追加事件

        :param db: 数据库会话
        :param obj: 步骤事件记录
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
        stmt = delete(AIBuddyStepEvent).where(AIBuddyStepEvent.run_id.in_(run_ids))
        return (await db.execute(stmt)).rowcount


ai_buddy_step_event_dao: CRUDAIBuddyStepEvent = CRUDAIBuddyStepEvent(AIBuddyStepEvent)
