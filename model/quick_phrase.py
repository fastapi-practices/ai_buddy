import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID

SYSTEM_QUICK_PHRASE_USER_ID = SYSTEM_OWNER_USER_ID


class AIBuddyQuickPhrase(Base):
    """AI 快捷短语表"""

    __tablename__ = 'ai_buddy_quick_phrase'

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    title: Mapped[str] = mapped_column(sa.String(128), comment='短语标题')
    content: Mapped[str] = mapped_column(UniversalText, comment='短语内容')
    sort: Mapped[int] = mapped_column(default=0, comment='排序')
