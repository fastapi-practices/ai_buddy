from datetime import datetime
from typing import Any

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key
from backend.plugin.ai_buddy.enums import AIBuddyFollowUpStatus


class AIBuddyFollowUp(Base):
    """AI 对话持久跟进队列"""

    __tablename__ = 'ai_buddy_follow_up'
    __table_args__ = (
        sa.UniqueConstraint('conversation_id', 'client_request_id', name='uk_ai_buddy_follow_up_request'),
        sa.Index('ix_ai_buddy_follow_up_queue', 'conversation_id', 'status', 'position'),
        {'comment': 'AI 对话持久跟进队列'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    conversation_id: Mapped[str] = mapped_column(sa.String(64), comment='对话 ID')
    user_id: Mapped[int] = mapped_column(sa.BigInteger, comment='用户 ID')
    client_request_id: Mapped[str] = mapped_column(sa.String(128), comment='客户端幂等 ID')
    content: Mapped[str] = mapped_column(UniversalText, comment='跟进文本')
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(sa.JSON, comment='AG-UI 附件内容')
    forwarded_props: Mapped[dict[str, Any]] = mapped_column(sa.JSON, comment='本轮运行参数')
    user_context: Mapped[dict[str, Any]] = mapped_column(sa.JSON, comment='提交时用户上下文')
    mode: Mapped[str] = mapped_column(sa.String(16), comment='请求处理方式')
    position: Mapped[int] = mapped_column(sa.Integer, comment='排队顺序')
    status: Mapped[str] = mapped_column(sa.String(16), default=AIBuddyFollowUpStatus.queued.value, comment='跟进状态')
    disposition: Mapped[str] = mapped_column(
        sa.String(16), default=AIBuddyFollowUpStatus.queued.value, comment='实际处理方式'
    )
    reason: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='降级或失败原因')
    run_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='派发运行 ID')
    message_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='回复消息 ID')
    claimed_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='派发认领时间')
    dispatch_committed: Mapped[bool] = mapped_column(default=False, comment='消息事务已提交')
