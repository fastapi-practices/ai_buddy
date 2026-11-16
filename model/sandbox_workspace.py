import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key


class AIBuddySandboxWorkspace(Base):
    """对话沙箱登记，记录当前对话正在使用的 OpenSandbox 实例，供跨进程接回和删除对话时销毁"""

    __tablename__ = 'ai_buddy_sandbox_workspace'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'conversation_id', name='uk_ai_buddy_sandbox_workspace_owner_conversation'),
        {'comment': 'AI 对话沙箱登记'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    conversation_id: Mapped[str] = mapped_column(sa.String(128), comment='对话 ID')
    sandbox_ref: Mapped[str] = mapped_column(sa.String(255), comment='OpenSandbox 实例 ID')
    permission_mode: Mapped[str] = mapped_column(sa.String(16), comment='创建时的权限模式')
