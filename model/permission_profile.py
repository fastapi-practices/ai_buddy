import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.enums import StatusType
from backend.common.model import Base, id_key


class AIBuddyPermissionProfile(Base):
    """AI 工具权限预设表"""

    __tablename__ = 'ai_buddy_permission_profile'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'code', 'deleted', name='uk_ai_buddy_permission_profile_user_code_deleted'),
        {'comment': 'AI 工具权限预设表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID，0 表示系统预设')
    code: Mapped[str] = mapped_column(sa.String(64), comment='预设编码')
    name: Mapped[str] = mapped_column(sa.String(128), comment='预设名称')
    description: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='预设说明')
    builtin: Mapped[bool] = mapped_column(default=False, server_default=sa.false(), comment='是否系统内置')
    status: Mapped[int] = mapped_column(
        default=StatusType.enable.value,
        server_default=str(StatusType.enable.value),
        comment='状态（0停用 1正常）',
    )
    sort: Mapped[int] = mapped_column(default=0, server_default='0', comment='排序')
