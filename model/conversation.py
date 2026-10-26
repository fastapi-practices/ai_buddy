from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.plugin.ai_buddy.enums import AIBuddyConversationSource, AIBuddyConversationSurface, AIBuddyOrigin


class AIBuddyConversation(Base):
    """AI 对话表"""

    __tablename__ = 'ai_buddy_conversation'
    __table_args__ = (
        sa.UniqueConstraint('conversation_id', 'deleted', name='uk_ai_buddy_conversation_conversation_id_deleted'),
        {'comment': 'AI 对话表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    conversation_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='对话 ID')
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    title: Mapped[str] = mapped_column(sa.String(256), comment='对话标题')
    provider_id: Mapped[int] = mapped_column(sa.BigInteger, comment='供应商 ID')
    model_id: Mapped[str] = mapped_column(sa.String(512), comment='模型 ID')
    agent_mode: Mapped[str | None] = mapped_column(sa.String(16), default=None, comment='最近一轮使用的会话模式')
    project_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='项目 ID')
    assistant_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='助手 ID')
    goal: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='对话目标')
    origin: Mapped[str] = mapped_column(
        sa.String(16),
        default=AIBuddyOrigin.web,
        server_default=AIBuddyOrigin.web,
        comment='对话来源',
    )
    surface: Mapped[str] = mapped_column(
        sa.String(16),
        default=AIBuddyConversationSurface.chat,
        server_default=AIBuddyConversationSurface.chat,
        index=True,
        comment='会话入口',
    )
    channel_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, index=True, comment='通道 ID')
    last_message_preview: Mapped[str | None] = mapped_column(sa.String(256), default=None, comment='最后一条消息预览')
    last_message_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='最后一条消息时间')
    pinned_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='置顶时间')
    archived_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='归档时间')
    source: Mapped[str] = mapped_column(
        sa.String(16),
        default=AIBuddyConversationSource.cloud,
        server_default=AIBuddyConversationSource.cloud,
        comment='会话事实源，cloud 以云端为准，local 以本机为准、云端仅保存元数据和备份',
    )
    revision: Mapped[int] = mapped_column(default=1, server_default='1', comment='可变字段修订号，用于并发修改冲突检测')
