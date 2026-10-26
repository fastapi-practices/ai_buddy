from datetime import datetime

import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, TimeZone, UniversalText, id_key


class AIBuddyMcpOauth(Base):
    """AI MCP 用户 OAuth 授权令牌表"""

    __tablename__ = 'ai_buddy_mcp_oauth'
    __table_args__ = (
        sa.UniqueConstraint('user_id', 'mcp_id', 'deleted', name='uk_ai_buddy_mcp_oauth_owner_mcp_deleted'),
        {'comment': 'AI MCP 用户 OAuth 授权令牌表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    user_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='用户 ID')
    mcp_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='MCP ID')
    server_url: Mapped[str] = mapped_column(sa.String(2048), comment='绑定 MCP 地址')
    config_generation: Mapped[str] = mapped_column(sa.String(64), comment='绑定平台配置版本')
    generation: Mapped[str] = mapped_column(sa.String(64), comment='用户授权版本')
    tokens_ciphertext: Mapped[str | None] = mapped_column(UniversalText, default=None, comment='加密用户令牌')
    enabled: Mapped[bool] = mapped_column(default=True, comment='是否启用 OAuth')
    expires_time: Mapped[datetime | None] = mapped_column(TimeZone, default=None, comment='访问令牌到期时间')
