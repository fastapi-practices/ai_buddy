import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.enums import StatusType
from backend.common.model import Base, id_key


class AIBuddyDefaultModel(Base):
    """AI 默认模型表"""

    __tablename__ = 'ai_buddy_default_model'
    __table_args__ = (
        sa.UniqueConstraint('kind', 'deleted', name='uk_ai_buddy_default_model_kind_deleted'),
        {'comment': 'AI 默认模型表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    kind: Mapped[str] = mapped_column(sa.String(32), comment='模型类型')
    provider_id: Mapped[int] = mapped_column(sa.BigInteger, comment='供应商 ID')
    model_id: Mapped[str] = mapped_column(sa.String(512), comment='模型 ID')
    status: Mapped[int] = mapped_column(default=StatusType.enable.value, comment='状态（0停用 1正常）')
