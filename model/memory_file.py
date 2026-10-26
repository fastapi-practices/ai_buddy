import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import DataClassBase, DateTimeMixin, UniversalText, id_key


class AIBuddyMemoryFile(DataClassBase, DateTimeMixin):
    """AI 记忆文件表"""

    __tablename__ = 'ai_buddy_memory_file'
    __table_args__ = {'comment': 'AI 记忆文件表'}

    id: Mapped[id_key] = mapped_column(init=False)
    path: Mapped[str] = mapped_column(sa.String(512), unique=True, index=True, comment='记忆路径')
    content: Mapped[str] = mapped_column(UniversalText, comment='记忆内容')
    version: Mapped[int] = mapped_column(sa.BigInteger, comment='版本')
    last_operation_id: Mapped[str | None] = mapped_column(sa.String(128), default=None, comment='最后操作 ID')
