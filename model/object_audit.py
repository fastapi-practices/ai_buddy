import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key


class AIBuddyObjectAudit(Base):
    """AI 统一对象访问审计表"""

    __tablename__ = 'ai_buddy_object_audit'
    __table_args__ = {'comment': 'AI 统一对象访问审计'}

    id: Mapped[id_key] = mapped_column(init=False)
    object_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='对象 ID')
    action: Mapped[str] = mapped_column(sa.String(32), comment='审计动作')
    actor_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='操作用户 ID，系统任务为空')
    detail: Mapped[dict[str, str | int | None] | None] = mapped_column(sa.JSON(), default=None, comment='审计详情')
