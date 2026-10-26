import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key

SYSTEM_EXPERT_USER_ID = 0


class AIBuddyExpert(Base):
    """AI 专家模板表"""

    __tablename__ = 'ai_buddy_expert'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', 'deleted', name='uk_ai_buddy_expert_user_id_name_deleted'),
        {'comment': 'AI 专家模板表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    name: Mapped[str] = mapped_column(sa.String(64), comment='专家名称')
    prompt: Mapped[str] = mapped_column(UniversalText, comment='角色提示词')
    description: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='专家描述')
    starters: Mapped[list[str] | None] = mapped_column(sa.JSON(), default=None, comment='开场白列表')
    mcp_ids: Mapped[list[int] | None] = mapped_column(sa.JSON(), default=None, comment='默认 MCP ID 列表')
    skill_ids: Mapped[list[int] | None] = mapped_column(sa.JSON(), default=None, comment='默认技能 ID 列表')
    knowledge_ids: Mapped[list[int] | None] = mapped_column(sa.JSON(), default=None, comment='默认知识库 ID 列表')
    sort: Mapped[int] = mapped_column(default=0, comment='排序')
    usage_count: Mapped[int] = mapped_column(default=0, server_default='0', comment='使用次数')
