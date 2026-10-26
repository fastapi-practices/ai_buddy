import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.enums import StatusType
from backend.common.model import Base, UniversalText, id_key


class AIBuddyModel(Base):
    """AI 模型表"""

    __tablename__ = 'ai_buddy_model'
    __table_args__ = (
        sa.UniqueConstraint(
            'provider_id', 'model_id', 'deleted', name='uk_ai_buddy_model_provider_id_model_id_deleted'
        ),
        {'comment': 'AI 模型表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    provider_id: Mapped[int] = mapped_column(sa.BigInteger, comment='供应商关联 ID')
    model_id: Mapped[str] = mapped_column(sa.String(512), comment='模型 ID')
    name: Mapped[str] = mapped_column(sa.String(256), comment='模型名称')
    kind: Mapped[str] = mapped_column(sa.String(32), comment='模型类型')
    status: Mapped[int] = mapped_column(default=StatusType.enable.value, comment='模型状态（0停用 1正常）')
    capabilities: Mapped[list[str]] = mapped_column(sa.JSON(), default_factory=list, comment='模型行为能力')
    input_modalities: Mapped[list[str] | None] = mapped_column(sa.JSON(), default=None, comment='模型输入模态')
    thinking_policy: Mapped[dict | None] = mapped_column(sa.JSON(), default=None, comment='模型级思考策略')
    context_window: Mapped[int | None] = mapped_column(default=None, comment='上下文窗口 token 数')
    max_output_tokens: Mapped[int | None] = mapped_column(default=None, comment='最大输出 token 数')
    sort: Mapped[int] = mapped_column(default=0, comment='排序')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
