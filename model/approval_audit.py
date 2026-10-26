from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, id_key
from backend.plugin.ai_buddy.enums import AIBuddyApprovalStatus


class AIBuddyApprovalAudit(Base):
    """AI 工具审批审计表"""

    __tablename__ = 'ai_buddy_approval_audit'

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='审批用户 ID')
    conversation_id: Mapped[str] = mapped_column(sa.String(64), index=True, comment='对话 ID')
    request_id: Mapped[str] = mapped_column(sa.String(64), unique=True, comment='审批请求 ID')
    run_id: Mapped[str] = mapped_column(sa.String(64), comment='运行 ID')
    tool_call_id: Mapped[str] = mapped_column(sa.String(256), comment='工具调用 ID')
    tool_name: Mapped[str] = mapped_column(sa.String(256), comment='工具名称')
    arguments_sha256: Mapped[str] = mapped_column(sa.String(64), comment='原始参数摘要')
    expires_time: Mapped[datetime | None] = mapped_column(TimeZone, comment='审批过期时间')
    status: Mapped[str] = mapped_column(sa.String(32), default=AIBuddyApprovalStatus.pending.value, comment='审批状态')
    resolved_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='审批结束时间')
