import httpx2

from pydantic_ai.retries import AsyncHTTPX2TenacityTransport, RetryConfig, wait_retry_after
from tenacity import retry_if_exception_type, stop_after_attempt

from backend.core.conf import settings


def build_retry_http_client() -> httpx2.AsyncClient:
    """构建带重试的 HTTP 客户端"""
    return httpx2.AsyncClient(
        transport=AsyncHTTPX2TenacityTransport(
            config=RetryConfig(
                retry=retry_if_exception_type((
                    httpx2.HTTPStatusError,
                    httpx2.TransportError,
                )),
                wait=wait_retry_after(),
                stop=stop_after_attempt(settings.AI_BUDDY_HTTP_MAX_RETRIES + 1),
                reraise=True,
            ),
            validate_response=lambda response: (
                response.raise_for_status() if response.status_code in {408, 409, 429, 500, 502, 503, 504} else None
            ),
        )
    )
