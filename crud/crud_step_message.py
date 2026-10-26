from collections.abc import Collection, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.step_message import AIBuddyStepMessage


class CRUDAIBuddyStepMessage(CRUDPlus[AIBuddyStepMessage]):
    """AI 步骤消息内容数据库操作类"""

    async def get_by_sha256s(self, db: AsyncSession, sha256s: Collection[str]) -> Sequence[AIBuddyStepMessage]:
        """
        通过摘要批量获取消息内容

        :param db: 数据库会话
        :param sha256s: 消息摘要集合
        :return:
        """
        if not sha256s:
            return []
        stmt = select(self.model).where(self.model.sha256.in_(sha256s))
        return (await db.execute(stmt)).scalars().all()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyStepMessage) -> None:
        """
        保存消息内容

        :param db: 数据库会话
        :param obj: 消息内容
        :return:
        """
        db.add(obj)
        await db.flush()


ai_buddy_step_message_dao: CRUDAIBuddyStepMessage = CRUDAIBuddyStepMessage(AIBuddyStepMessage)
