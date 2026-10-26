from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.step_run import AIBuddyStepRun


class CRUDAIBuddyStepRun(CRUDPlus[AIBuddyStepRun]):
    """AI 步骤运行数据库操作类"""

    async def get_by_run_id(self, db: AsyncSession, run_id: str) -> AIBuddyStepRun | None:
        """
        通过运行 ID 获取运行记录

        :param db: 数据库会话
        :param run_id: 运行 ID
        :return:
        """
        return await self.select_model_by_column(db, run_id=run_id)

    async def get_list(
        self, db: AsyncSession, *, parent_run_id: str | None, conversation_id: str | None
    ) -> Sequence[AIBuddyStepRun]:
        """
        按父运行和对话筛选运行记录，按开始时间升序

        :param db: 数据库会话
        :param parent_run_id: 父运行 ID
        :param conversation_id: 对话 ID
        :return:
        """
        stmt = select(self.model)
        if parent_run_id is not None:
            stmt = stmt.where(self.model.parent_run_id == parent_run_id)
        if conversation_id is not None:
            stmt = stmt.where(self.model.conversation_id == conversation_id)
        return (await db.execute(stmt.order_by(self.model.started_time.asc(), self.model.id.asc()))).scalars().all()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyStepRun) -> None:
        """
        创建运行记录

        :param db: 数据库会话
        :param obj: 运行记录
        :return:
        """
        db.add(obj)
        await db.flush()

    async def get_run_ids(self, db: AsyncSession, conversation_id: str) -> Sequence[str]:
        """
        获取对话下全部运行 ID

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        stmt = select(self.model.run_id).where(self.model.conversation_id == conversation_id)
        return (await db.execute(stmt)).scalars().all()

    @staticmethod
    async def delete_by_conversation_id(db: AsyncSession, conversation_id: str) -> int:
        """
        物理删除对话下的运行记录

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        stmt = delete(AIBuddyStepRun).where(AIBuddyStepRun.conversation_id == conversation_id)
        return (await db.execute(stmt)).rowcount


ai_buddy_step_run_dao: CRUDAIBuddyStepRun = CRUDAIBuddyStepRun(AIBuddyStepRun)
