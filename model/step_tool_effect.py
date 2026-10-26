from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key


class AIBuddyStepToolEffect(Base):
    """AI 步骤工具副作用台账表"""

    __tablename__ = 'ai_buddy_step_tool_effect'
    __table_args__ = (
        sa.UniqueConstraint('run_id', 'tool_call_id', name='uk_ai_buddy_step_tool_effect_run_call'),
        {'comment': 'AI 步骤工具副作用台账'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    run_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='运行 ID')
    tool_call_id: Mapped[str] = mapped_column(sa.String(256), comment='工具调用 ID')
    tool_name: Mapped[str] = mapped_column(sa.String(256), comment='工具名称')
    status: Mapped[str] = mapped_column(sa.String(32), comment='副作用状态')
    started_time: Mapped[datetime] = mapped_column(TimeZone, comment='调用开始时间')
    ended_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='调用结束时间')
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(256), default=None, comment='幂等键')
    effect_summary: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='副作用摘要')
