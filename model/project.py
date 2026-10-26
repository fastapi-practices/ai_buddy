import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key


class AIBuddyProject(Base):
    """AI 项目表"""

    __tablename__ = 'ai_buddy_project'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', 'deleted', name='uk_ai_buddy_project_user_id_name_deleted'),
        {'comment': 'AI 项目表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    name: Mapped[str] = mapped_column(sa.String(64), comment='项目名称')
    sort: Mapped[int] = mapped_column(default=0, comment='排序')
    archived: Mapped[bool] = mapped_column(default=False, comment='是否归档')
