import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.enums import DataBaseType
from backend.common.model import Base, id_key
from backend.core.conf import settings
from backend.plugin.ai_buddy.enums import AIBuddyWorkspaceFileState


class AIBuddyWorkspaceFile(Base):
    """AI 工作区文件清单表"""

    __tablename__ = 'ai_buddy_workspace_file'
    __table_args__ = (
        sa.UniqueConstraint(
            'user_id',
            'workspace_id',
            'relative_path_hash' if DataBaseType.mysql == settings.DATABASE_TYPE else 'relative_path',
            'deleted',
            name='uk_ai_buddy_workspace_file_owner_path_deleted',
        ),
        {'comment': 'AI 工作区文件清单表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    workspace_id: Mapped[str] = mapped_column(sa.String(128), index=True, comment='工作区 ID')
    relative_path: Mapped[str] = mapped_column(
        sa.String(2048).with_variant(sa.String(2048, collation='utf8mb4_bin'), 'mysql'),
        comment='相对路径',
    )
    if DataBaseType.mysql == settings.DATABASE_TYPE:
        relative_path_hash: Mapped[bytes] = mapped_column(
            sa.BINARY(32),
            sa.Computed('unhex(sha2(relative_path, 256))', persisted=True),
            init=False,
            comment='相对路径 SHA-256 摘要',
        )
    object_key: Mapped[str | None] = mapped_column(sa.String(1024), default=None, comment='对象键')
    storage_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='对象存储 ID')
    size: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='文件字节数')
    sha256: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='文件 SHA-256 摘要')
    mime_type: Mapped[str | None] = mapped_column(sa.String(128), default=None, comment='媒体类型')
    state: Mapped[str] = mapped_column(
        sa.String(32),
        default=AIBuddyWorkspaceFileState.ready.value,
        server_default=AIBuddyWorkspaceFileState.ready.value,
        comment='文件状态',
    )
    revision: Mapped[int] = mapped_column(sa.BigInteger, default=0, server_default='0', comment='文件版本')
