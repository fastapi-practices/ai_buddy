import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.ai_buddy.enums import AIBuddyKnowledgeFileType


class AIBuddyKnowledge(Base):
    """AI 知识文档表"""

    __tablename__ = 'ai_buddy_knowledge'

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    knowledge_base_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='知识库 ID')
    title: Mapped[str] = mapped_column(sa.String(256), comment='知识标题')
    source: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='知识来源')
    file_type: Mapped[AIBuddyKnowledgeFileType] = mapped_column(
        sa.Enum(
            AIBuddyKnowledgeFileType,
            name='ck_ai_buddy_knowledge_file_type',
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            length=32,
        ),
        default=AIBuddyKnowledgeFileType.txt,
        server_default=AIBuddyKnowledgeFileType.txt.value,
        comment='文档类型',
    )
    object_key: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='对象键')
    storage_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='对象存储 ID')
    provider_id: Mapped[int | None] = mapped_column(sa.BigInteger, default=None, comment='向量化供应商 ID')
    model_id: Mapped[str | None] = mapped_column(sa.String(512), default=None, comment='向量化模型 ID')
