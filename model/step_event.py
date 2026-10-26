from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key


class AIBuddyStepEvent(Base):
    """AI 步骤事件表"""

    __tablename__ = 'ai_buddy_step_event'
    __table_args__ = (
        sa.UniqueConstraint('run_id', 'idempotency_key', name='uk_ai_buddy_step_event_run_key'),
        {'comment': 'AI 步骤事件'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    run_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='运行 ID')
    kind: Mapped[str] = mapped_column(sa.String(32), comment='事件类型')
    step_index: Mapped[int] = mapped_column(comment='步骤序号')
    event_time: Mapped[datetime] = mapped_column(TimeZone, comment='事件时间')
    conversation_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='对话 ID')
    parent_run_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='父运行 ID')
    agent_name: Mapped[str | None] = mapped_column(sa.String(128), default=None, comment='Agent 名称')
    tool_call_id: Mapped[str | None] = mapped_column(sa.String(256), default=None, comment='工具调用 ID')
    tool_name: Mapped[str | None] = mapped_column(sa.String(256), default=None, comment='工具名称')
    error: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='错误信息')
    event_metadata: Mapped[dict[str, str] | None] = mapped_column(sa.JSON(), default=None, comment='事件元数据')
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(256), default=None, comment='边界幂等键')
