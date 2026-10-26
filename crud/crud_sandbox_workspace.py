import sqlalchemy as sa

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.sandbox_workspace import AIBuddySandboxWorkspace


class CRUDAIBuddySandboxWorkspace(CRUDPlus[AIBuddySandboxWorkspace]):
    """对话沙箱登记数据库操作类"""

    async def get(self, db: AsyncSession, user_id: int, conversation_id: str) -> AIBuddySandboxWorkspace | None:
        """
        锁定并获取当前用户的对话沙箱登记

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :return:
        """
        return await db.scalar(
            sa
            .select(self.model)
            .where(self.model.user_id == user_id, self.model.conversation_id == conversation_id)
            .with_for_update()
        )

    @staticmethod
    async def save(
        db: AsyncSession,
        record: AIBuddySandboxWorkspace | None,
        *,
        user_id: int,
        conversation_id: str,
        provider: str,
        sandbox_ref: str,
        permission_mode: str,
    ) -> AIBuddySandboxWorkspace:
        """
        新建或覆盖对话沙箱登记

        :param db: 数据库会话
        :param record: 已有登记
        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param provider: 沙箱服务商
        :param sandbox_ref: 沙箱引用
        :param permission_mode: 权限模式
        :return:
        """
        if record is None:
            record = AIBuddySandboxWorkspace(
                user_id=user_id,
                conversation_id=conversation_id,
                provider=provider,
                sandbox_ref=sandbox_ref,
                permission_mode=permission_mode,
            )
            db.add(record)
        else:
            record.provider = provider
            record.sandbox_ref = sandbox_ref
            record.permission_mode = permission_mode
        await db.flush()
        return record

    @staticmethod
    async def delete(db: AsyncSession, record: AIBuddySandboxWorkspace) -> None:
        """
        删除登记

        :param db: 数据库会话
        :param record: 登记
        :return:
        """
        await db.delete(record)
        await db.flush()


ai_buddy_sandbox_workspace_dao: CRUDAIBuddySandboxWorkspace = CRUDAIBuddySandboxWorkspace(AIBuddySandboxWorkspace)
