import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key


class AIBuddyObjectRef(Base):
    """AI 统一对象引用表"""

    __tablename__ = 'ai_buddy_object_ref'
    __table_args__ = (
        sa.UniqueConstraint('object_id', 'owner_type', 'owner_id', name='uk_ai_buddy_object_ref_owner'),
        {'comment': 'AI 统一对象引用'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    object_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='对象 ID')
    owner_type: Mapped[str] = mapped_column(sa.String(32), comment='引用方类型')
    owner_id: Mapped[str] = mapped_column(sa.String(128), comment='引用方 ID')
