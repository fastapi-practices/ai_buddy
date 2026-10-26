from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key


class AIBuddyStepSnapshot(Base):
    """AI 步骤快照表"""

    __tablename__ = 'ai_buddy_step_snapshot'
    __table_args__ = (
        sa.UniqueConstraint('run_id', 'idempotency_key', name='uk_ai_buddy_step_snapshot_run_key'),
        {'comment': 'AI 步骤快照'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    run_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='运行 ID')
    step_index: Mapped[int] = mapped_column(comment='步骤序号')
    snapshot_time: Mapped[datetime] = mapped_column(TimeZone, comment='快照时间')
    state: Mapped[str] = mapped_column(sa.String(32), comment='快照状态')
    message_refs: Mapped[list[str]] = mapped_column(sa.JSON(), comment='消息内容摘要引用')
    conversation_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='对话 ID')
    parent_run_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='父运行 ID')
    agent_name: Mapped[str | None] = mapped_column(sa.String(128), default=None, comment='Agent 名称')
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(256), default=None, comment='边界幂等键')
