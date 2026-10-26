import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID

SYSTEM_SKILL_USER_ID = SYSTEM_OWNER_USER_ID


class AIBuddySkill(Base):
    """AI 技能表"""

    __tablename__ = 'ai_buddy_skill'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', 'deleted', name='uk_ai_buddy_skill_user_id_name_deleted'),
        {'comment': 'AI 技能表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    name: Mapped[str] = mapped_column(sa.String(128), comment='技能名称')
    description: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='技能描述')
    version: Mapped[str] = mapped_column(sa.String(32), default='0.1.0', server_default='0.1.0', comment='技能版本')
    object_key: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='对象键')
    storage_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='对象存储 ID')
