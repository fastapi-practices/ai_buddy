import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key


class AIBuddyKnowledgeBase(Base):
    """AI 知识库表"""

    __tablename__ = 'ai_buddy_knowledge_base'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', 'deleted', name='uk_ai_buddy_knowledge_base_user_id_name_deleted'),
        {'comment': 'AI 知识库表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    name: Mapped[str] = mapped_column(sa.String(128), comment='知识库名称')
    description: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='知识库描述')
    provider_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='向量化供应商 ID')
    model_id: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='向量化模型 ID')
