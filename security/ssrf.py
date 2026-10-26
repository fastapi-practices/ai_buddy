import asyncio
import socket

from collections.abc import Iterable
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

import httpcore2
import httpx2

from backend.common.exception import errors

_BLOCKED_HOSTS = frozenset({'localhost', 'metadata.google.internal'})


def validate_public_http_url(url: str) -> None:
    """
    校验出站 HTTP URL，禁止回环和私网地址

    :param url: 待校验 URL
    :return:
    """
    parsed = urlparse(url)
    if parsed.scheme not in {'http', 'https'}:
        raise errors.RequestError(msg='出站地址仅支持 http/https')
    host = (parsed.hostname or '').strip().lower().rstrip('.')
    if not host:
        raise errors.RequestError(msg='出站地址缺少主机名')
    if host in _BLOCKED_HOSTS or host.endswith('.local'):
        raise errors.RequestError(msg='出站地址不允许访问内网')
    try:
        address = ip_address(host)
    except ValueError:
        return
    if not address.is_global or address.is_multicast:
        raise errors.RequestError(msg='出站地址不允许访问内网')


class _PublicNetworkBackend(httpcore2.AnyIOBackend):
    """TCP 只连接本次检查过的数字地址，避免 DNS 检查与连接之间重绑定"""

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore2.SOCKET_OPTION] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        """
        校验解析地址后建立 TCP 连接

        :param host: 目标主机
        :param port: 目标端口
        :param timeout: 连接超时时间
        :param local_address: 本地绑定地址
        :param socket_options: 套接字选项
        :return:
        """
        try:
            async with asyncio.timeout(timeout):
                records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
                addresses = list(dict.fromkeys(record[4][0] for record in records))
                if not addresses:
                    raise httpcore2.ConnectError('MCP 端点未解析到可用地址')
                for address in addresses:
                    parsed = ip_address(address)
                    if not parsed.is_global or parsed.is_multicast:
                        raise errors.RequestError(msg='出站地址解析到了非公网地址')
                last_error: Exception | None = None
                for address in addresses:
                    try:
                        stream = await super().connect_tcp(
                            address,
                            port,
                            timeout=timeout,
                            local_address=local_address,
                            socket_options=socket_options,
                        )
                    except (httpcore2.ConnectError, httpcore2.ConnectTimeout) as exc:
                        last_error = exc
                        continue
                    peer = stream.get_extra_info('server_addr')
                    if not peer or ip_address(peer[0]) != ip_address(address):
                        await stream.aclose()
                        raise errors.RequestError(msg='出站连接地址与已校验地址不一致')
                    return stream
                raise last_error or httpcore2.ConnectError('MCP 端点连接失败')
        except TimeoutError as exc:
            raise httpcore2.ConnectTimeout('MCP 端点连接超时') from exc
        except socket.gaierror as exc:
            raise httpcore2.ConnectError('MCP 端点域名解析失败') from exc


class _PublicHTTPTransport(httpx2.AsyncHTTPTransport):
    """保留原始 Host 和 TLS 主机名，仅替换底层 TCP 地址解析"""

    def __init__(self) -> None:
        super().__init__(trust_env=False)
        # HTTPX 未暴露 network_backend 参数，复用其协议适配并注入受限连接池
        self._pool = httpcore2.AsyncConnectionPool(
            ssl_context=httpx2.create_ssl_context(trust_env=False),
            network_backend=_PublicNetworkBackend(),
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        """
        校验目标地址后发送 HTTP 请求

        :param request: HTTP 请求
        :return:
        """
        validate_public_http_url(str(request.url))
        return await super().handle_async_request(request)


def create_public_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx2.Timeout | None = None,
    auth: httpx2.Auth | None = None,
    **kwargs: Any,
) -> httpx2.AsyncClient:
    """
    供 MCP 两种 HTTP 传输共用，代理不能绕过公网地址检查

    :param headers: 请求头
    :param timeout: 超时时间
    :param auth: 认证信息
    :param kwargs: 额外关键字参数
    :return:
    """
    return httpx2.AsyncClient(
        headers=headers,
        timeout=timeout or httpx2.Timeout(30, read=300),
        auth=auth,
        follow_redirects=bool(kwargs.get('follow_redirects', True)),
        trust_env=False,
        transport=_PublicHTTPTransport(),
    )
