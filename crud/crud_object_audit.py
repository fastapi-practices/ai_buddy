from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.object_audit import AIBuddyObjectAudit


class CRUDAIBuddyObjectAudit(CRUDPlus[AIBuddyObjectAudit]):
    """AI 统一对象审计数据库操作类"""

    async def get_all(self, db: AsyncSession, object_id: int) -> Sequence[AIBuddyObjectAudit]:
        """
        按时间顺序获取对象审计记录

        :param db: 数据库会话
        :param object_id: 对象 ID
        :return:
        """
        stmt = select(self.model).where(self.model.object_id == object_id).order_by(self.model.id.asc())
        return (await db.execute(stmt)).scalars().all()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyObjectAudit) -> None:
        """
        追加审计记录

        :param db: 数据库会话
        :param obj: 审计记录
        :return:
        """
        db.add(obj)
        await db.flush()


ai_buddy_object_audit_dao: CRUDAIBuddyObjectAudit = CRUDAIBuddyObjectAudit(AIBuddyObjectAudit)
