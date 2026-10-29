import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID

SYSTEM_SUBAGENT_USER_ID = SYSTEM_OWNER_USER_ID


class AIBuddySubagent(Base):
    """AI 子代理目录表"""

    __tablename__ = 'ai_buddy_subagent'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', 'deleted', name='uk_ai_buddy_subagent_user_id_name_deleted'),
        {'comment': 'AI 子代理目录表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    name: Mapped[str] = mapped_column(sa.String(64), comment='子代理名称')
    description: Mapped[str] = mapped_column(sa.String(512), comment='子代理描述')
    prompt: Mapped[str] = mapped_column(UniversalText, comment='角色提示词')
    sort: Mapped[int] = mapped_column(default=0, comment='排序')
