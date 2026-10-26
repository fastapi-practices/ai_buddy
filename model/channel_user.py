from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key


class AIBuddyChannelUser(Base):
    """AI 通道用户映射表"""

    __tablename__ = 'ai_buddy_channel_user'
    __table_args__ = (
        sa.UniqueConstraint(
            'channel_id',
            'external_id',
            'deleted',
            name='uk_ai_buddy_channel_user_channel_id_external_id_deleted',
        ),
        {'comment': 'AI 通道用户映射表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    channel_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='通道 ID')
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='系统用户 ID')
    external_id: Mapped[str] = mapped_column(sa.String(128), comment='平台用户标识')
    extra: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON(), default=None, comment='附加映射信息')
