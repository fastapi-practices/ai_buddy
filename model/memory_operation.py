import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import DataClassBase, DateTimeMixin, id_key


class AIBuddyMemoryOperation(DataClassBase, DateTimeMixin):
    """AI 记忆操作回执表"""

    __tablename__ = 'ai_buddy_memory_operation'
    __table_args__ = {'comment': 'AI 记忆操作回执表'}

    id: Mapped[id_key] = mapped_column(init=False)
    operation_id: Mapped[str] = mapped_column(sa.String(128), unique=True, index=True, comment='操作 ID')
    fingerprint: Mapped[str] = mapped_column(sa.String(128), comment='参数指纹')
    version: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='结果版本')
    existed: Mapped[bool] = mapped_column(default=False, comment='操作前是否存在')
    completed: Mapped[bool] = mapped_column(default=False, comment='是否完成')
