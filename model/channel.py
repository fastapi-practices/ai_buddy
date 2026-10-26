from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.enums import StatusType
from backend.common.model import Base, id_key
from backend.plugin.ai_buddy.enums import AIBuddyChannelType


class AIBuddyChannel(Base):
    """AI 通道表"""

    __tablename__ = 'ai_buddy_channel'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', 'deleted', name='uk_ai_buddy_channel_user_id_name_deleted'),
        sa.Index('ix_ai_buddy_channel_owner_id', 'user_id'),
        {'comment': 'AI 通道表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, comment='用户 ID')
    name: Mapped[str] = mapped_column(sa.String(64), comment='通道名称')
    type: Mapped[str] = mapped_column(sa.String(32), default=AIBuddyChannelType.feishu, comment='通道类型')
    config: Mapped[dict[str, Any] | None] = mapped_column(sa.JSON(), default=None, comment='通道配置')
    status: Mapped[int] = mapped_column(default=StatusType.enable.value, comment='状态（0停用 1正常）')
    show_thinking: Mapped[bool] = mapped_column(default=True, comment='是否展示思考过程')
    show_tool_hints: Mapped[bool] = mapped_column(default=True, comment='是否展示工具调用提示')
