from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.security.ssrf import validate_public_http_url


class AIBuddyMcpOAuthCallbackQueryParam(SchemaBase):
    """AI MCP OAuth 回调查询参数"""

    state: str = Field(min_length=32, max_length=128, description='授权状态值')
    code: str | None = Field(None, max_length=8192, description='授权码')
    error: str | None = Field(None, max_length=256, description='授权服务返回的错误码')


class UpdateAIBuddyMcpOauthParam(SchemaBase):
    """配置平台统一注册的 OAuth 授权码客户端"""

    model_config = ConfigDict(extra='forbid')

    enabled: bool = Field(True, description='是否启用 MCP OAuth')
    authorization_url: str = Field(min_length=1, max_length=2048, description='授权端点 HTTPS 地址')
    token_url: str = Field(min_length=1, max_length=2048, description='令牌端点 HTTPS 地址')
    client_id: str = Field(min_length=1, max_length=512, description='已注册的客户端 ID')
    client_secret: str | None = Field(None, max_length=8192, description='客户端密钥，省略时保留当前密钥')
    scope: str = Field('', max_length=2048, description='以空格分隔的权限范围')
    token_endpoint_auth_method: Literal['none', 'client_secret_post', 'client_secret_basic'] = Field(
        'none', description='令牌端点客户端认证方式'
    )

    @field_validator('authorization_url', 'token_url')
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        """
        限制凭据交换地址为公网 HTTPS，拒绝 URL 内嵌凭据和片段

        :param value: OAuth 端点
        :return:
        """
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('OAuth 端点必须是没有内嵌凭据和片段的 HTTPS 地址')
        validate_public_http_url(value)
        return value


class GetAIBuddyMcpOauthDetail(SchemaBase):
    """当前用户的 MCP OAuth 连接状态"""

    configured: bool = Field(description='平台是否已配置并启用 OAuth')
    connected: bool = Field(description='是否已连接用户账号')
    expires_time: datetime | None = Field(None, description='访问令牌到期时间')


class GetAIBuddyMcpOauthConfigDetail(SchemaBase):
    """后台 OAuth 配置详情，不返回令牌和客户端密钥"""

    configured: bool = Field(description='平台是否已保存 OAuth 客户端配置')
    enabled: bool = Field(False, description='是否启用 MCP OAuth')
    redirect_uri: str = Field(description='需向服务商登记的服务端回调地址')
    authorization_url: str | None = Field(None, description='授权端点')
    token_url: str | None = Field(None, description='令牌端点')
    client_id: str | None = Field(None, description='客户端 ID')
    has_client_secret: bool = Field(False, description='是否已保存客户端密钥')
    scope: str = Field('', description='权限范围')
    token_endpoint_auth_method: str = Field('none', description='客户端认证方式')


class GetAIBuddyMcpOauthAuthorizeDetail(SchemaBase):
    """浏览器授权入口"""

    authorization_url: str = Field(description='本次授权链接')
    expires_seconds: int = Field(description='本次授权有效秒数')
