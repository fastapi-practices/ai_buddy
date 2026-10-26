from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.ai_buddy.enums import AIBuddyMessageStatus, AIBuddyOrigin


class AIBuddyMessage(Base):
    """AI 消息表"""

    __tablename__ = 'ai_buddy_message'

    id: Mapped[id_key] = mapped_column(init=False)
    conversation_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='对话 ID')
    provider_id: Mapped[int] = mapped_column(sa.BigInteger, comment='供应商 ID')
    model_id: Mapped[str] = mapped_column(sa.String(512), comment='模型 ID')
    message_index: Mapped[int] = mapped_column(index=True, comment='消息索引')
    role: Mapped[str] = mapped_column(sa.String(16), comment='消息角色')
    model_messages: Mapped[list[dict[str, Any]]] = mapped_column(sa.JSON(), comment='原始 Pydantic 模型消息列表')
    origin: Mapped[str] = mapped_column(
        sa.String(16),
        default=AIBuddyOrigin.web,
        server_default=AIBuddyOrigin.web,
        comment='消息来源',
    )
    client_message_id: Mapped[str | None] = mapped_column(
        sa.String(128), index=True, default=None, comment='客户端消息 ID，用于重发幂等'
    )
    turn_context: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON(), default=None, comment='本轮实际组合')
    status: Mapped[str] = mapped_column(
        sa.String(16),
        default=AIBuddyMessageStatus.success,
        comment='消息状态',
    )
