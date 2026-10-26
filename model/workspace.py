import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.ai_buddy.enums import AIBuddyWorkspaceState


class AIBuddyWorkspace(Base):
    """AI 工作区表"""

    __tablename__ = 'ai_buddy_workspace'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'workspace_id', 'deleted', name='uk_ai_buddy_workspace_owner_workspace_deleted'),
        {'comment': 'AI 工作区表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    workspace_id: Mapped[str] = mapped_column(sa.String(128), comment='工作区 ID')
    name: Mapped[str] = mapped_column(sa.String(256), comment='工作区名称')
    backend: Mapped[str] = mapped_column(sa.String(32), comment='工作区后端')
    object_prefix: Mapped[str] = mapped_column(sa.String(512), comment='对象前缀')
    revision: Mapped[int] = mapped_column(sa.BigInteger, default=0, server_default='0', comment='工作区版本')
    state: Mapped[str] = mapped_column(
        sa.String(32),
        default=AIBuddyWorkspaceState.ready.value,
        server_default=AIBuddyWorkspaceState.ready.value,
        comment='工作区状态',
    )
