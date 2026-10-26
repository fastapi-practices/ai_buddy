from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.ai_buddy.crud.crud_conversation_audit import ai_buddy_conversation_audit_dao
from backend.plugin.ai_buddy.enums import AIBuddyConversationAuditAction
from backend.plugin.ai_buddy.model.conversation_audit import AIBuddyConversationAudit


class AIBuddyConversationAuditService:
    """AI 会话审计服务类，记录导出、导入、删除和同步访问"""

    @staticmethod
    async def record(
        *,
        db: AsyncSession,
        user_id: int,
        conversation_id: str,
        action: AIBuddyConversationAuditAction,
        client: str | None = None,
        detail: dict[str, str | int | None] | None = None,
    ) -> None:
        """
        追加会话审计记录

        :param db: 数据库会话
        :param user_id: 操作用户 ID
        :param conversation_id: 对话 ID
        :param action: 审计动作
        :param client: 访问来源
        :param detail: 审计详情
        :return:
        """
        await ai_buddy_conversation_audit_dao.create(
            db,
            AIBuddyConversationAudit(
                user_id=user_id,
                conversation_id=conversation_id,
                action=action.value,
                client=client[:256] if client else None,
                detail=detail,
            ),
        )

    @staticmethod
    async def get_all(
        *, db: AsyncSession, user_id: int, conversation_id: str | None, before: int | None, limit: int
    ) -> Sequence[AIBuddyConversationAudit]:
        """
        读取当前用户的会话审计

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 限定的对话 ID
        :param before: 上一页最小审计 ID
        :param limit: 返回条数
        :return:
        """
        return await ai_buddy_conversation_audit_dao.get_all(
            db, user_id, conversation_id=conversation_id, before=before, limit=limit
        )


ai_buddy_conversation_audit_service: AIBuddyConversationAuditService = AIBuddyConversationAuditService()
