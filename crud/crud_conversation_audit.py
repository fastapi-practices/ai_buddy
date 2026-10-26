from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.conversation_audit import AIBuddyConversationAudit


class CRUDAIBuddyConversationAudit(CRUDPlus[AIBuddyConversationAudit]):
    """AI 会话审计数据库操作类"""

    async def get_all(
        self, db: AsyncSession, user_id: int, *, conversation_id: str | None, before: int | None, limit: int
    ) -> Sequence[AIBuddyConversationAudit]:
        """
        按时间倒序读取当前用户的会话审计

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 限定的对话 ID
        :param before: 上一页最小审计 ID
        :param limit: 返回条数
        :return:
        """
        stmt = select(self.model).where(self.model.user_id == user_id)
        if conversation_id is not None:
            stmt = stmt.where(self.model.conversation_id == conversation_id)
        if before is not None:
            stmt = stmt.where(self.model.id < before)
        return (await db.execute(stmt.order_by(self.model.id.desc()).limit(limit))).scalars().all()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyConversationAudit) -> None:
        """
        追加审计记录

        :param db: 数据库会话
        :param obj: 审计记录
        :return:
        """
        db.add(obj)
        await db.flush()


ai_buddy_conversation_audit_dao: CRUDAIBuddyConversationAudit = CRUDAIBuddyConversationAudit(AIBuddyConversationAudit)
