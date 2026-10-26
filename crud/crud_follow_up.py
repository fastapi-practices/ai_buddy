from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.enums import AIBuddyFollowUpStatus
from backend.plugin.ai_buddy.model.follow_up import AIBuddyFollowUp


class CRUDAIBuddyFollowUp(CRUDPlus[AIBuddyFollowUp]):
    """持久跟进数据库操作"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyFollowUp | None:
        """
        获取跟进记录，包含已删除项以校验派发状态

        :param db: 数据库会话
        :param pk: 跟进 ID
        :return:
        """
        return await db.get(self.model, pk)

    async def get_by_request_id(
        self, db: AsyncSession, conversation_id: str, request_id: str
    ) -> AIBuddyFollowUp | None:
        """读取幂等记录，包含已删除项

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param request_id: 请求 ID
        :return:
        """
        return await db.scalar(
            select(self.model)
            .where(
                self.model.conversation_id == conversation_id,
                self.model.client_request_id == request_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def get_list(
        self,
        db: AsyncSession,
        conversation_id: str,
        *,
        for_update: bool = False,
    ) -> list[AIBuddyFollowUp]:
        """读取未删除的跟进，变更路径使用当前读

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param for_update: 是否锁定记录
        :return:
        """
        stmt = (
            select(self.model)
            .where(
                self.model.conversation_id == conversation_id,
                self.model.deleted == 0,
            )
            .order_by(self.model.position, self.model.id)
            .execution_options(populate_existing=True)
        )
        if for_update:
            stmt = stmt.with_for_update()
        return list((await db.scalars(stmt)).all())

    async def get_due_conversations(self, db: AsyncSession) -> list[str]:
        """读取有待执行或待确认派发的会话

        :param db: 数据库会话
        :return:
        """
        return list(
            (
                await db.scalars(
                    select(self.model.conversation_id)
                    .where(
                        self.model.deleted == 0,
                        (self.model.status == AIBuddyFollowUpStatus.queued)
                        | ((self.model.status == AIBuddyFollowUpStatus.dispatched) & ~self.model.dispatch_committed),
                    )
                    .distinct()
                )
            ).all()
        )

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyFollowUp) -> None:
        """
        保存跟进记录

        :param db: 数据库会话
        :param obj: 跟进记录
        :return:
        """
        db.add(obj)
        await db.flush()


ai_buddy_follow_up_dao = CRUDAIBuddyFollowUp(AIBuddyFollowUp)
