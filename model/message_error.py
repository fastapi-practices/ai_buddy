from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key


class AIBuddyMessageError(Base):
    """AI 消息错误表"""

    __tablename__ = 'ai_buddy_message_error'
    __table_args__ = (
        sa.UniqueConstraint('message_id', 'deleted', name='uk_ai_buddy_message_error_message_deleted'),
        {'comment': 'AI 消息错误'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    message_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='消息 ID')
    conversation_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='对话 ID')
    message: Mapped[str] = mapped_column(UniversalText, comment='错误信息')
    detail: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON(), default=None, comment='错误详情')
