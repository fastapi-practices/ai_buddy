import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key


class AIBuddyStepMessage(Base):
    """AI 步骤消息内容表，按摘要去重"""

    __tablename__ = 'ai_buddy_step_message'
    __table_args__ = (sa.UniqueConstraint('sha256', name='uk_ai_buddy_step_message_sha256'), {'comment': 'AI 步骤消息'})

    id: Mapped[id_key] = mapped_column(init=False)
    sha256: Mapped[str] = mapped_column(sa.String(64), comment='消息 JSON 的 SHA-256 摘要')
    content: Mapped[str] = mapped_column(UniversalText, comment='消息 JSON')
