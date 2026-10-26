import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.enums import StatusType
from backend.common.model import Base, UniversalText, id_key


class AIBuddyProvider(Base):
    """AI 供应商表"""

    __tablename__ = 'ai_buddy_provider'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'name', 'deleted', name='uk_ai_buddy_provider_user_id_name_deleted'),
        {'comment': 'AI 供应商表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    name: Mapped[str] = mapped_column(sa.String(256), comment='供应商名称')
    type: Mapped[int] = mapped_column(comment='供应商类型')
    api_key: Mapped[str] = mapped_column(UniversalText, comment='接口密钥')
    api_host: Mapped[str] = mapped_column(sa.String(512), comment='接口地址')
    user_id: Mapped[int] = mapped_column(sa.BigInteger, default=0, index=True, comment='用户 ID')
    status: Mapped[int] = mapped_column(default=StatusType.enable.value, comment='供应商状态（0停用 1正常）')
    remark: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='备注')
