from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key


class AIBuddyStepRun(Base):
    """AI 步骤运行表"""

    __tablename__ = 'ai_buddy_step_run'
    __table_args__ = (sa.UniqueConstraint('run_id', name='uk_ai_buddy_step_run_run_id'), {'comment': 'AI 步骤运行'})

    id: Mapped[id_key] = mapped_column(init=False)
    run_id: Mapped[str] = mapped_column(sa.String(64), comment='运行 ID')
    started_time: Mapped[datetime] = mapped_column(TimeZone, index=True, comment='运行开始时间')
    conversation_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, default=None, comment='对话 ID')
    parent_run_id: Mapped[str | None] = mapped_column(sa.String(64), index=True, default=None, comment='父运行 ID')
    agent_name: Mapped[str | None] = mapped_column(sa.String(128), default=None, comment='Agent 名称')
    run_metadata: Mapped[dict[str, str] | None] = mapped_column(sa.JSON(), default=None, comment='运行元数据')
    registration_id: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='注册调用 ID')
