from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.plugin.ai_buddy.enums import AIBuddyObjectState


class AIBuddyObject(Base):
    """AI 统一对象表"""

    __tablename__ = 'ai_buddy_object'
    __table_args__ = (
        sa.UniqueConstraint('location', 'storage_id', 'object_key', name='uk_ai_buddy_object_location_key'),
        {'comment': 'AI 统一对象'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='所属用户 ID')
    kind: Mapped[str] = mapped_column(sa.String(32), index=True, comment='对象类型')
    location: Mapped[str] = mapped_column(sa.String(16), comment='对象位置')
    object_key: Mapped[str] = mapped_column(sa.String(512), comment='对象键')
    storage_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='对象存储 ID')
    sha256: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='内容 SHA-256 摘要')
    size: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='字节数')
    mime_type: Mapped[str | None] = mapped_column(sa.String(128), default=None, comment='媒体类型')
    ref_count: Mapped[int] = mapped_column(default=0, comment='引用计数')
    state: Mapped[str] = mapped_column(
        sa.String(16), index=True, default=AIBuddyObjectState.active.value, comment='生命周期状态'
    )
    tombstoned_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='墓碑时间')
    delete_after_time: Mapped[datetime | None] = mapped_column(
        TimeZone, index=True, default=None, comment='宽限期结束后才可物理删除'
    )
    physically_deleted_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='物理删除时间')
