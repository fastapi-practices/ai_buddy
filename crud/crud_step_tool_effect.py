from collections.abc import Collection, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.step_tool_effect import AIBuddyStepToolEffect


class CRUDAIBuddyStepToolEffect(CRUDPlus[AIBuddyStepToolEffect]):
    """AI 步骤工具副作用台账数据库操作类"""

    async def get_by_call_id(self, db: AsyncSession, run_id: str, tool_call_id: str) -> AIBuddyStepToolEffect | None:
        """
        通过工具调用 ID 获取台账记录

        :param db: 数据库会话
        :param run_id: 运行 ID
        :param tool_call_id: 工具调用 ID
        :return:
        """
        return await self.select_model_by_column(db, run_id=run_id, tool_call_id=tool_call_id)

    async def get_unresolved(self, db: AsyncSession, run_id: str) -> Sequence[AIBuddyStepToolEffect]:
        """
        获取崩溃后状态未知的台账记录

        :param db: 数据库会话
        :param run_id: 运行 ID
        :return:
        """
        stmt = (
            select(self.model)
            .where(self.model.run_id == run_id, self.model.status == 'started')
            .order_by(self.model.id.asc())
        )
        return (await db.execute(stmt)).scalars().all()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyStepToolEffect) -> None:
        """
        新增台账记录

        :param db: 数据库会话
        :param obj: 台账记录
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
        stmt = delete(AIBuddyStepToolEffect).where(AIBuddyStepToolEffect.run_id.in_(run_ids))
        return (await db.execute(stmt)).rowcount


ai_buddy_step_tool_effect_dao: CRUDAIBuddyStepToolEffect = CRUDAIBuddyStepToolEffect(AIBuddyStepToolEffect)
