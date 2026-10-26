import sqlalchemy as sa

from sqlalchemy.orm import Mapped, mapped_column

from backend.common.model import Base, UniversalText, id_key


class AIBuddyMcpOauthConfig(Base):
    """AI 内置 MCP 平台 OAuth 客户端配置表"""

    __tablename__ = 'ai_buddy_mcp_oauth_config'
    __table_args__ = (
        sa.UniqueConstraint('mcp_id', 'deleted', name='uk_ai_buddy_mcp_oauth_config_mcp_deleted'),
        {'comment': 'AI 内置 MCP 平台 OAuth 客户端配置表'},
    )

    id: Mapped[id_key] = mapped_column(init=False)
    mcp_id: Mapped[int] = mapped_column(sa.BigInteger, index=True, comment='内置 MCP ID')
    server_url: Mapped[str] = mapped_column(sa.String(2048), comment='绑定 MCP 地址')
    generation: Mapped[str] = mapped_column(sa.String(64), comment='平台配置版本')
    config_ciphertext: Mapped[str] = mapped_column(UniversalText, comment='加密 OAuth 客户端配置')
    enabled: Mapped[bool] = mapped_column(default=True, comment='是否启用 OAuth')
