import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.ai_buddy.enums import AIBuddyArtifactKind, AIBuddyArtifactState, AIBuddyArtifactStorageBackend


class AIBuddyArtifact(Base):
    """AI 产物表"""

    __tablename__ = 'ai_buddy_artifact'

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    title: Mapped[str] = mapped_column(sa.String(256), comment='产物标题')
    kind: Mapped[AIBuddyArtifactKind] = mapped_column(
        sa.Enum(
            AIBuddyArtifactKind,
            name='ck_ai_buddy_artifact_kind',
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            length=64,
        ),
        comment='产物类型',
    )
    object_key: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='对象键')
    storage_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='对象存储 ID')
    storage_backend: Mapped[str] = mapped_column(
        sa.String(32),
        default=AIBuddyArtifactStorageBackend.s3.value,
        server_default=AIBuddyArtifactStorageBackend.s3.value,
        comment='存储后端',
    )
    workspace_id: Mapped[str | None] = mapped_column(sa.String(128), default=None, comment='工作区 ID')
    relative_path: Mapped[str | None] = mapped_column(sa.String(2048), default=None, comment='工作区相对路径')
    mime_type: Mapped[str | None] = mapped_column(sa.String(128), default=None, comment='媒体类型')
    size: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='文件字节数')
    sha256: Mapped[str | None] = mapped_column(sa.String(64), default=None, comment='文件 SHA-256 摘要')
    state: Mapped[str] = mapped_column(
        sa.String(32),
        default=AIBuddyArtifactState.ready.value,
        server_default=AIBuddyArtifactState.ready.value,
        comment='产物状态',
    )
