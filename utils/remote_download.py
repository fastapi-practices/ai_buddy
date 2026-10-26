import asyncio

from collections.abc import Sequence
from dataclasses import dataclass
from email.message import Message
from urllib.parse import unquote, urlparse

import httpx2

from backend.common.exception import errors
from backend.plugin.ai_buddy.security.ssrf import create_public_http_client, validate_public_http_url

_MAX_REDIRECTS = 5


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """已下载的远程文件"""

    data: bytes
    content_type: str
    filename: str


def match_content_type(content_type: str, allowed: Sequence[str]) -> bool:
    """
    判断媒体类型是否命中允许列表，以 / 结尾的项按前缀匹配，其余项要求完全一致

    :param content_type: 不含参数的媒体类型
    :param allowed: 允许列表
    :return:
    """
    return any(content_type.startswith(item) if item.endswith('/') else content_type == item for item in allowed)


async def download_public_file(
    *, url: str, max_bytes: int, allowed_types: Sequence[str], timeout: float = 30
) -> RemoteFile:
    """
    从公网下载文件，只允许 http/https，禁止内网、回环和重定向绕过，并限制大小与类型

    :param url: 远程地址
    :param max_bytes: 文件字节数上限
    :param allowed_types: 允许的媒体类型
    :param timeout: 单次网络操作超时秒数，整体下载时限为其 4 倍
    :return:
    """
    validate_public_http_url(url)
    client = create_public_http_client(timeout=httpx2.Timeout(timeout))
    client.max_redirects = _MAX_REDIRECTS
    try:
        async with asyncio.timeout(timeout * 4), client, client.stream('GET', url) as response:
            response.raise_for_status()
            content_type = response.headers.get('content-type', '').split(';', 1)[0].strip().lower()
            if not match_content_type(content_type, allowed_types):
                raise errors.RequestError(msg=f'不支持的文件类型：{content_type or "未知"}')
            declared = response.headers.get('content-length')
            if declared is not None and declared.isdigit() and int(declared) > max_bytes:
                raise errors.RequestError(msg='远程文件超过大小上限')
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise errors.RequestError(msg='远程文件超过大小上限')
                chunks.append(chunk)
            filename = _filename(response=response)
    except errors.RequestError:
        raise
    except (httpx2.HTTPError, TimeoutError) as exc:
        raise errors.RequestError(msg='远程文件下载失败') from exc
    return RemoteFile(data=b''.join(chunks), content_type=content_type, filename=filename)


def _filename(*, response: httpx2.Response) -> str:
    """
    优先取 Content-Disposition 中的文件名，否则取最终地址路径的最后一段

    :param response: 响应
    :return:
    """
    message = Message()
    message['content-disposition'] = response.headers.get('content-disposition', '')
    name = message.get_filename() or unquote(urlparse(str(response.url)).path.rsplit('/', 1)[-1])
    return name.replace('/', '_').replace('\\', '_')[:255] or 'download'
