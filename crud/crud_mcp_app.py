from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.ai_buddy.model.message import AIBuddyMessage


async def get_latest_mcp_ids(db: AsyncSession, conversation_id: str) -> set[int]:
    """
    读取会话最近一轮明确启用的 MCP

    :param db: 数据库会话
    :param conversation_id: 会话 ID
    :return:
    """
    row = await db.scalar(
        select(AIBuddyMessage)
        .where(
            AIBuddyMessage.conversation_id == conversation_id,
            AIBuddyMessage.role == 'user',
            AIBuddyMessage.deleted == 0,
        )
        .order_by(AIBuddyMessage.message_index.desc(), AIBuddyMessage.id.desc())
        .limit(1)
    )
    context = row.turn_context if row and isinstance(row.turn_context, dict) else {}
    return {value for value in context.get('mcp_ids', []) if isinstance(value, int) and not isinstance(value, bool)}
