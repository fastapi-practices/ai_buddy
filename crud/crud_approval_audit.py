from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.enums import AIBuddyApprovalStatus
from backend.plugin.ai_buddy.model.approval_audit import AIBuddyApprovalAudit


class CRUDAIBuddyApprovalAudit(CRUDPlus[AIBuddyApprovalAudit]):
    """AI 工具审批审计数据库操作类"""

    async def get_by_request_id(self, db: AsyncSession, user_id: int, request_id: str) -> AIBuddyApprovalAudit | None:
        """查询当前用户的请求记录

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param request_id: 请求 ID
        :return:
        """
        return (
            await db.execute(
                select(self.model).where(self.model.user_id == user_id, self.model.request_id == request_id)
            )
        ).scalar_one_or_none()

    async def get_all(
        self, db: AsyncSession, user_id: int, *, before: int | None = None, limit: int = 100
    ) -> Sequence[AIBuddyApprovalAudit]:
        """按用户读取最近审批记录

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param before: 上一页最小 ID
        :param limit: 返回条数
        :return:
        """
        stmt = select(self.model).where(self.model.user_id == user_id)
        if before is not None:
            stmt = stmt.where(self.model.id < before)
        return (await db.execute(stmt.order_by(self.model.id.desc()).limit(limit))).scalars().all()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyApprovalAudit) -> None:
        """保存审批请求

        :param db: 数据库会话
        :param obj: 审计记录
        :return:
        """
        db.add(obj)
        await db.flush()

    async def resolve(
        self, db: AsyncSession, user_id: int, request_id: str, status: AIBuddyApprovalStatus, resolved_time: datetime
    ) -> None:
        """结束待处理记录，保留首次已确认的用户决定

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param request_id: 审批请求 ID
        :param status: 结束状态
        :param resolved_time: 结束时间
        :return:
        """
        statuses = (
            (AIBuddyApprovalStatus.pending, AIBuddyApprovalStatus.cancelled, AIBuddyApprovalStatus.expired)
            if status in (AIBuddyApprovalStatus.approved, AIBuddyApprovalStatus.denied)
            else (AIBuddyApprovalStatus.pending,)
        )
        await db.execute(
            update(self.model)
            .where(self.model.user_id == user_id, self.model.request_id == request_id, self.model.status.in_(statuses))
            .values(status=status, resolved_time=resolved_time)
        )


ai_buddy_approval_audit_dao: CRUDAIBuddyApprovalAudit = CRUDAIBuddyApprovalAudit(AIBuddyApprovalAudit)
