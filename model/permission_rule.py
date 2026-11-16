import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, id_key
from backend.plugin.ai_buddy.enums import AIBuddyPermissionMatchKind, AIBuddyToolPolicy


class AIBuddyPermissionRule(Base):
    """AI 工具权限规则表"""

    __tablename__ = 'ai_buddy_permission_rule'
    __table_args__ = (
        sa.UniqueConstraint(
            'profile_id',
            'tool_name',
            'match_kind',
            'match_value',
            'deleted',
            name='uk_ai_buddy_permission_rule_profile_tool_match_deleted',
        ),
        {'comment': 'AI 工具权限规则表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    profile_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='权限预设 ID')
    tool_name: Mapped[str] = mapped_column(sa.String(128), comment='工具名，* 表示默认规则')
    action: Mapped[str] = mapped_column(
        sa.String(16),
        default=AIBuddyToolPolicy.ask,
        server_default=AIBuddyToolPolicy.ask,
        comment='允许策略（allow / ask / deny）',
    )
    match_kind: Mapped[str] = mapped_column(
        sa.String(32),
        default=AIBuddyPermissionMatchKind.any,
        server_default=AIBuddyPermissionMatchKind.any,
        comment='匹配方式',
    )
    match_value: Mapped[str] = mapped_column(
        sa.String(512),
        default='',
        server_default='',
        comment='匹配值，首版 any 固定为空字符串',
    )
    priority: Mapped[int] = mapped_column(default=0, server_default='0', comment='同工具规则优先级')
    enabled: Mapped[bool] = mapped_column(default=True, server_default=sa.true(), comment='是否启用')
