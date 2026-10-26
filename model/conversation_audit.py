import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key


class AIBuddyConversationAudit(Base):
    """AI 会话审计表"""

    __tablename__ = 'ai_buddy_conversation_audit'
    __table_args__ = {'comment': 'AI 会话审计'}

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='操作用户 ID')
    conversation_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='对话 ID')
    action: Mapped[str] = mapped_column(sa.String(16), comment='审计动作')
    client: Mapped[str | None] = mapped_column(sa.String(256), default=None, comment='访问来源，取自 User-Agent')
    detail: Mapped[dict[str, str | int | None] | None] = mapped_column(sa.JSON(), default=None, comment='审计详情')
