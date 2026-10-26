import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key

# 系统默认助手归属，所有用户可读可绑定，仅超级管理员可改
SYSTEM_ASSISTANT_USER_ID = 0


class AIBuddyAssistant(Base):
    """AI 助手表"""

    __tablename__ = 'ai_buddy_assistant'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', 'deleted', name='uk_ai_buddy_assistant_user_id_name_deleted'),
        {'comment': 'AI 助手表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    name: Mapped[str] = mapped_column(sa.String(64), comment='助手名称')
    prompt: Mapped[str] = mapped_column(UniversalText, comment='角色提示词')
    description: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='助手描述')
    category: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='助手分类编码')
    starters: Mapped[list[str] | None] = mapped_column(sa.JSON(), default=None, comment='开场白列表')
    sort: Mapped[int] = mapped_column(default=0, comment='排序')
    usage_count: Mapped[int] = mapped_column(default=0, server_default='0', comment='使用次数')
