from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.enums import StatusType
from backend.common.model import Base, TimeZone, UniversalText, id_key
from backend.plugin.ai_buddy.cron.task_type import CRON_NAME_MAX_LEN


class AIBuddyCron(Base):
    """AI 定时任务表"""

    __tablename__ = 'ai_buddy_cron'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', 'deleted', name='uk_ai_buddy_cron_user_id_name_deleted'),
        {'comment': 'AI 定时任务表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    conversation_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='对话 ID')
    name: Mapped[str] = mapped_column(sa.String(CRON_NAME_MAX_LEN), comment='任务名称')
    trigger: Mapped[str] = mapped_column(sa.String(128), comment='调度表达式')
    prompt: Mapped[str] = mapped_column(UniversalText, comment='提示词')
    fresh_thread: Mapped[bool] = mapped_column(default=False, comment='每次执行是否新开对话')
    provider_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='覆盖供应商 ID')
    model_id: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='覆盖模型 ID')
    mcp_ids: Mapped[list[int] | None] = mapped_column(sa.JSON(), default=None, comment='本轮 MCP ID 列表')
    status: Mapped[int] = mapped_column(default=StatusType.enable.value, comment='状态（0停用 1正常）')
    last_run_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='最近执行时间')
    last_status: Mapped[str | None] = mapped_column(sa.String(16), default=None, comment='最近执行状态')
    last_error: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='最近执行错误')
