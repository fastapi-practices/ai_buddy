import asyncio
import base64
import hashlib
import json
import secrets

from datetime import timedelta
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import httpx2

from cryptography.fernet import Fernet
from mcp.shared.auth import OAuthToken
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.database.redis import redis_client
from backend.plugin.ai_buddy.crud.crud_mcp_oauth import ai_buddy_mcp_oauth_dao
from backend.plugin.ai_buddy.crud.crud_mcp_oauth_config import ai_buddy_mcp_oauth_config_dao
from backend.plugin.ai_buddy.model.mcp import AIBuddyMcp
from backend.plugin.ai_buddy.model.mcp_oauth import AIBuddyMcpOauth
from backend.plugin.ai_buddy.model.mcp_oauth_config import AIBuddyMcpOauthConfig
from backend.plugin.ai_buddy.schema.mcp_oauth import (
    GetAIBuddyMcpOauthAuthorizeDetail,
    GetAIBuddyMcpOauthConfigDetail,
    GetAIBuddyMcpOauthDetail,
    UpdateAIBuddyMcpOauthParam,
)
from backend.plugin.ai_buddy.security.ssrf import create_public_http_client
from backend.plugin.ai_buddy.service.mcp_service import ai_buddy_mcp_service
from backend.utils.timezone import timezone

_STATE_PREFIX = 'ai-buddy:mcp-oauth:state'
_RELEASE_LOCK = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"


class AIBuddyMcpOauthService:
    """AI MCP 授权码和令牌生命周期服务类"""

    @staticmethod
    def redirect_uri() -> str:
        """读取部署显式配置的回调地址，禁止从请求 Host 推断"""
        value = settings.AI_BUDDY_MCP_OAUTH_REDIRECT_URI.strip()
        if value:
            parsed = urlsplit(value)
            if (
                (
                    parsed.scheme != 'https'
                    and not (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'})
                )
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
                or parsed.query
            ):
                raise errors.RequestError(msg='AI_BUDDY_MCP_OAUTH_REDIRECT_URI 必须是 HTTPS 回调地址')
        return value

    @staticmethod
    async def get(*, db: AsyncSession, user_id: int, mcp_id: int) -> GetAIBuddyMcpOauthDetail:
        """
        读取平台是否已配置及当前用户的连接状态

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param mcp_id: MCP ID
        :return:
        """
        mcp = await ai_buddy_mcp_service.get(db=db, pk=mcp_id, user_id=user_id)
        config = await ai_buddy_mcp_oauth_config_dao.get(db, mcp_id)
        row = await ai_buddy_mcp_oauth_dao.get(db, user_id, mcp_id)
        configured = bool(
            config and config.enabled and config.server_url == mcp.url and mcp.type != 0 and mcp.user_id == 0
        )
        connected = bool(
            configured
            and row
            and row.enabled
            and row.tokens_ciphertext
            and row.server_url == mcp.url
            and row.config_generation == config.generation
        )
        return GetAIBuddyMcpOauthDetail(
            configured=configured, connected=connected, expires_time=row.expires_time if connected else None
        )

    async def get_config(
        self, *, db: AsyncSession, user_id: int, mcp_id: int, is_superuser: bool
    ) -> GetAIBuddyMcpOauthConfigDetail:
        """
        读取后台统一配置，不返回客户端密钥

        :param db: 数据库会话
        :param user_id: 管理员 ID
        :param mcp_id: 内置 MCP ID
        :param is_superuser: 是否超级管理员
        :return:
        """
        if not is_superuser:
            raise errors.ForbiddenError(msg='只有超级管理员可以管理内置 MCP OAuth 配置')
        mcp = await ai_buddy_mcp_service.get(db=db, pk=mcp_id, user_id=user_id, is_superuser=True)
        if mcp.user_id != 0:
            raise errors.RequestError(msg='后台 OAuth 配置仅支持内置 MCP')
        row = await ai_buddy_mcp_oauth_config_dao.get(db, mcp_id)
        if row is None:
            return GetAIBuddyMcpOauthConfigDetail(configured=False, redirect_uri=self.redirect_uri())
        config = json.loads(self._credential_cipher().decrypt(row.config_ciphertext.encode()))
        return GetAIBuddyMcpOauthConfigDetail(
            configured=True,
            enabled=bool(row.enabled and row.server_url == mcp.url and mcp.type != 0),
            redirect_uri=self.redirect_uri(),
            authorization_url=config['authorization_url'],
            token_url=config['token_url'],
            client_id=config['client_id'],
            has_client_secret=bool(config.get('client_secret')),
            scope=config.get('scope', ''),
            token_endpoint_auth_method=config['token_endpoint_auth_method'],
        )

    async def update_config(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        mcp_id: int,
        is_superuser: bool,
        obj: UpdateAIBuddyMcpOauthParam,
    ) -> None:
        """
        保存后台统一客户端配置并使所有旧个人授权失效

        :param db: 数据库会话
        :param user_id: 管理员 ID
        :param mcp_id: 内置 MCP ID
        :param is_superuser: 是否超级管理员
        :param obj: 客户端配置
        :return:
        """
        if not is_superuser:
            raise errors.ForbiddenError(msg='只有超级管理员可以管理内置 MCP OAuth 配置')
        mcp = await ai_buddy_mcp_service.get(db=db, pk=mcp_id, user_id=user_id, is_superuser=True)
        if mcp.user_id != 0:
            raise errors.RequestError(msg='后台 OAuth 配置仅支持内置 MCP')
        if mcp.type == 0 or not mcp.url or urlsplit(mcp.url).scheme != 'https':
            raise errors.RequestError(msg='OAuth 仅支持 HTTPS 远程 MCP')
        row = await ai_buddy_mcp_oauth_config_dao.get(db, mcp_id)
        config = obj.model_dump(exclude={'enabled'})
        if obj.client_secret is None and row is not None:
            old = json.loads(self._credential_cipher().decrypt(row.config_ciphertext.encode()))
            config['client_secret'] = old.get('client_secret')
        if config['token_endpoint_auth_method'] != 'none' and not config.get('client_secret'):
            raise errors.RequestError(msg='当前认证方式需要客户端密钥')
        ciphertext = self._credential_cipher().encrypt(json.dumps(config).encode()).decode()
        generation = secrets.token_hex(16)
        if row is None:
            await ai_buddy_mcp_oauth_config_dao.create(
                db,
                AIBuddyMcpOauthConfig(
                    mcp_id=mcp_id,
                    server_url=mcp.url,
                    generation=generation,
                    config_ciphertext=ciphertext,
                    enabled=obj.enabled,
                ),
            )
        else:
            updated = await ai_buddy_mcp_oauth_config_dao.update(
                db,
                mcp_id,
                row.generation,
                {
                    'server_url': mcp.url,
                    'generation': generation,
                    'config_ciphertext': ciphertext,
                    'enabled': obj.enabled,
                },
            )
            if not updated:
                raise errors.ConflictError(msg='OAuth 配置已变更，请重试')
        await ai_buddy_mcp_oauth_dao.invalidate(db, mcp_id, secrets.token_hex(16))

    async def authorize(self, *, db: AsyncSession, user_id: int, mcp_id: int) -> GetAIBuddyMcpOauthAuthorizeDetail:
        """
        生成一次性 PKCE 授权请求

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param mcp_id: MCP ID
        :return:
        """
        mcp = await ai_buddy_mcp_service.get(db=db, pk=mcp_id, user_id=user_id)
        config_row = await ai_buddy_mcp_oauth_config_dao.get(db, mcp_id)
        row = await ai_buddy_mcp_oauth_dao.get(db, user_id, mcp_id)
        redirect_uri = self.redirect_uri()
        if not redirect_uri:
            raise errors.RequestError(msg='请管理员先配置 AI_BUDDY_MCP_OAUTH_REDIRECT_URI，并在服务商登记回调地址')
        if (
            mcp.user_id != 0
            or mcp.type == 0
            or config_row is None
            or not config_row.enabled
            or config_row.server_url != mcp.url
        ):
            raise errors.RequestError(msg='请管理员先配置并启用当前内置 MCP 的 OAuth')
        config = json.loads(self._credential_cipher().decrypt(config_row.config_ciphertext.encode()))
        verifier = secrets.token_urlsafe(48)
        state = secrets.token_urlsafe(32)
        generation = secrets.token_hex(16)
        if row is None:
            await ai_buddy_mcp_oauth_dao.create(
                db,
                AIBuddyMcpOauth(
                    user_id=user_id,
                    mcp_id=mcp_id,
                    server_url=mcp.url,
                    config_generation=config_row.generation,
                    generation=generation,
                ),
            )
        else:
            updated = await ai_buddy_mcp_oauth_dao.update(
                db,
                user_id,
                mcp_id,
                row.generation,
                {
                    'server_url': mcp.url,
                    'config_generation': config_row.generation,
                    'generation': generation,
                    'enabled': True,
                    'tokens_ciphertext': None,
                    'expires_time': None,
                },
            )
            if not updated:
                raise errors.ConflictError(msg='OAuth 连接已变更，请重试')
        await redis_client.set(
            f'{_STATE_PREFIX}:{state}',
            self
            ._credential_cipher()
            .encrypt(
                json.dumps({
                    'user_id': user_id,
                    'mcp_id': mcp_id,
                    'generation': generation,
                    'config_generation': config_row.generation,
                    'verifier': verifier,
                    'redirect_uri': redirect_uri,
                }).encode()
            )
            .decode(),
            ex=600,
        )
        parsed = urlsplit(config['authorization_url'])
        params = dict(parse_qsl(parsed.query))
        params.update({
            'response_type': 'code',
            'client_id': config['client_id'],
            'redirect_uri': redirect_uri,
            'state': state,
            'code_challenge': base64
            .urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b'=')
            .decode(),
            'code_challenge_method': 'S256',
            'resource': config_row.server_url,
        })
        if config.get('scope'):
            params['scope'] = config['scope']
        return GetAIBuddyMcpOauthAuthorizeDetail(
            authorization_url=urlunsplit(parsed._replace(query=urlencode(params))), expires_seconds=600
        )

    async def callback(self, *, state: str, code: str | None, error: str | None) -> None:
        """
        消费一次性授权状态并保存当前配置版本的令牌

        :param state: 一次性授权状态
        :param code: 授权码
        :param error: 服务商拒绝授权状态
        :return:
        """
        raw = await redis_client.getdel(f'{_STATE_PREFIX}:{state}')
        if not raw:
            raise errors.RequestError(msg='OAuth 授权已过期或已使用，请重新连接')
        pending = json.loads(self._credential_cipher().decrypt(raw.encode() if isinstance(raw, str) else raw))
        if error or not code:
            raise errors.RequestError(msg='OAuth 授权未完成，请返回应用重试')
        user_id, mcp_id = pending['user_id'], pending['mcp_id']
        async with async_db_session() as db:
            mcp = await ai_buddy_mcp_service.get(db=db, pk=mcp_id, user_id=user_id)
            row = await ai_buddy_mcp_oauth_dao.get(db, user_id, mcp_id)
            config_row = await ai_buddy_mcp_oauth_config_dao.get(db, mcp_id)
        if (
            row is None
            or not row.enabled
            or row.generation != pending['generation']
            or row.server_url != mcp.url
            or mcp.type == 0
            or mcp.user_id != 0
            or config_row is None
            or not config_row.enabled
            or config_row.server_url != mcp.url
            or config_row.generation != pending['config_generation']
            or row.config_generation != config_row.generation
        ):
            raise errors.ConflictError(msg='连接配置已变更，请重新授权')
        config = json.loads(self._credential_cipher().decrypt(config_row.config_ciphertext.encode()))
        tokens = await self._exchange(
            config=config,
            resource=row.server_url,
            data={
                'grant_type': 'authorization_code',
                'code': code,
                'redirect_uri': pending['redirect_uri'],
                'code_verifier': pending['verifier'],
            },
        )
        await self._save_tokens(row=row, tokens=tokens)

    @staticmethod
    async def disconnect(*, db: AsyncSession, user_id: int, mcp_id: int) -> None:
        """
        删除本应用保存的用户令牌，旧回调不能重新连接

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param mcp_id: MCP ID
        :return:
        """
        await ai_buddy_mcp_service.get(db=db, pk=mcp_id, user_id=user_id)
        row = await ai_buddy_mcp_oauth_dao.get(db, user_id, mcp_id)
        if row is not None:
            updated = await ai_buddy_mcp_oauth_dao.update(
                db,
                user_id,
                mcp_id,
                row.generation,
                {
                    'generation': secrets.token_hex(16),
                    'tokens_ciphertext': None,
                    'expires_time': None,
                    'enabled': False,
                },
            )
            if not updated:
                raise errors.ConflictError(msg='OAuth 配置已变更，请重试断开连接')

    async def headers(self, *, mcp: AIBuddyMcp, user_id: int) -> dict[str, str]:
        """
        读取当前用户令牌并在过期前刷新，不重试 MCP 工具执行

        :param mcp: 已校验访问权限的 MCP
        :param user_id: 用户 ID
        :return:
        """
        headers = {str(key): str(value) for key, value in (mcp.headers or {}).items()}
        if mcp.type == 0:
            return headers
        async with async_db_session() as db:
            config_row = await ai_buddy_mcp_oauth_config_dao.get(db, mcp.id)
            row = await ai_buddy_mcp_oauth_dao.get(db, user_id, mcp.id)
        if config_row is None or not config_row.enabled:
            return headers
        if config_row.server_url != mcp.url or mcp.user_id != 0:
            raise errors.RequestError(msg=f'请管理员更新 MCP OAuth 配置: {mcp.name}')
        if (
            row is None
            or not row.enabled
            or row.server_url != mcp.url
            or not row.tokens_ciphertext
            or row.config_generation != config_row.generation
        ):
            raise errors.RequestError(msg=f'请重新连接 MCP OAuth: {mcp.name}')
        tokens = json.loads(self._credential_cipher().decrypt(row.tokens_ciphertext.encode()))
        if row.expires_time is not None and row.expires_time <= timezone.now() + timedelta(seconds=30):
            tokens = await self._refresh_tokens(mcp=mcp, row=row)
        headers = {key: value for key, value in headers.items() if key.lower() != 'authorization'}
        headers['Authorization'] = f'Bearer {tokens["access_token"]}'
        return headers

    async def _refresh_tokens(self, *, mcp: AIBuddyMcp, row: AIBuddyMcpOauth) -> dict[str, Any]:
        """
        持有用户刷新锁期间重验配置、交换并保存令牌

        :param mcp: 当前 MCP
        :param row: 待刷新的个人连接版本
        :return:
        """
        lock_key = f'ai-buddy:mcp-oauth:refresh:{row.user_id}:{mcp.id}'
        lock_id = secrets.token_hex(16)
        if not await redis_client.set(lock_key, lock_id, nx=True, ex=30):
            raise errors.ConflictError(msg='MCP OAuth 正在刷新，请稍后重试')
        try:
            async with async_db_session() as db:
                current = await ai_buddy_mcp_oauth_dao.get(db, row.user_id, mcp.id)
                config_row = await ai_buddy_mcp_oauth_config_dao.get(db, mcp.id)
            if (
                current is None
                or current.generation != row.generation
                or not current.enabled
                or not current.tokens_ciphertext
                or config_row is None
                or not config_row.enabled
                or config_row.generation != row.config_generation
                or current.config_generation != config_row.generation
                or config_row.server_url != mcp.url
            ):
                raise errors.ConflictError(msg='MCP OAuth 连接已变更')
            row = current
            tokens = json.loads(self._credential_cipher().decrypt(row.tokens_ciphertext.encode()))
            if row.expires_time is not None and row.expires_time <= timezone.now() + timedelta(seconds=30):
                if not tokens.get('refresh_token'):
                    raise errors.RequestError(msg=f'MCP OAuth 已过期，请重新连接: {mcp.name}')
                config = json.loads(self._credential_cipher().decrypt(config_row.config_ciphertext.encode()))
                refreshed = await self._exchange(
                    config=config,
                    resource=row.server_url,
                    data={'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token']},
                )
                if not refreshed.get('refresh_token'):
                    refreshed['refresh_token'] = tokens['refresh_token']
                await self._save_tokens(row=row, tokens=refreshed)
                tokens = refreshed
            return tokens
        finally:
            await redis_client.eval(_RELEASE_LOCK, 1, lock_key, lock_id)

    @staticmethod
    async def _exchange(*, config: dict[str, Any], resource: str, data: dict[str, str]) -> dict[str, Any]:
        """
        经受限网络交换令牌，限制响应大小并复用 MCP SDK 令牌契约

        :param config: 已配置客户端
        :param resource: 绑定的 MCP 资源地址
        :param data: 授权码或刷新参数
        :return:
        """
        data = {**data, 'client_id': config['client_id'], 'resource': resource}
        method = config['token_endpoint_auth_method']
        auth = None
        if method == 'client_secret_basic':
            auth = httpx2.BasicAuth(quote_plus(config['client_id']), quote_plus(config['client_secret']))
        elif method == 'client_secret_post':
            data['client_secret'] = config['client_secret']
        try:
            async with (
                asyncio.timeout(15),
                create_public_http_client(timeout=httpx2.Timeout(15), auth=auth, follow_redirects=False) as client,
                client.stream('POST', config['token_url'], data=data) as response,
            ):
                if not response.is_success:
                    raise errors.RequestError(msg='OAuth 令牌交换失败，请检查客户端配置或重新授权')
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > 64 * 1024:
                        raise errors.RequestError(msg='OAuth 令牌响应超过大小限制')
            decoded = json.loads(payload)
            if str(decoded.get('token_type', '')).lower() == 'bearer':
                decoded['token_type'] = 'Bearer'
            tokens = OAuthToken.model_validate(decoded).model_dump(exclude_none=True)
            if (
                not tokens['access_token']
                or any(char in tokens['access_token'] for char in '\r\n')
                or not 0 <= tokens.get('expires_in', 0) <= 366 * 24 * 60 * 60
            ):
                raise ValueError('invalid token or lifetime')
        except errors.BaseExceptionError:
            raise
        except Exception as exc:
            raise errors.RequestError(msg='OAuth 令牌交换失败，请检查服务商配置后重试') from exc
        return tokens

    async def _save_tokens(self, *, row: AIBuddyMcpOauth, tokens: dict[str, Any]) -> None:
        """
        按配置版本写入加密令牌，拒绝已断开或已更改的连接

        :param row: 原始配置版本
        :param tokens: 服务商返回的令牌
        :return:
        """
        expires = tokens.get('expires_in')
        values = {
            'tokens_ciphertext': self._credential_cipher().encrypt(json.dumps(tokens).encode()).decode(),
            'expires_time': timezone.now() + timedelta(seconds=expires) if expires is not None else None,
            'enabled': True,
        }
        async with async_db_session.begin() as db:
            updated = await ai_buddy_mcp_oauth_dao.save_tokens(db, row, values)
            if not updated:
                raise errors.ConflictError(msg='OAuth 配置已变更，请重新连接')

    @staticmethod
    def _credential_cipher() -> Fernet:
        """使用独立用途的派生密钥加密连接器凭据"""
        key = hashlib.sha256(('ai-buddy-mcp-oauth:' + settings.TOKEN_SECRET_KEY).encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))


ai_buddy_mcp_oauth_service: AIBuddyMcpOauthService = AIBuddyMcpOauthService()
