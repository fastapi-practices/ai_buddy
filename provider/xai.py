from inspect import isawaitable
from typing import ClassVar
from urllib.parse import urlsplit

import httpx2

from pydantic_ai.images import ImageGenerationModel
from pydantic_ai.images.xai import XaiImageGenerationModel
from pydantic_ai.models import Model
from pydantic_ai.models.xai import XaiModel, XaiModelSettings
from pydantic_ai.providers.xai import XaiProvider
from xai_sdk import AsyncClient

from backend.plugin.ai_buddy.enums import AIBuddyProviderType
from backend.plugin.ai_buddy.provider.base import (
    ProviderAdapter,
    ProviderCapabilities,
    ProviderModelSnapshot,
    normalize_provider_api_host,
)
from backend.plugin.ai_buddy.utils.model_listing import list_openai_compat_models


class XaiAdapter(ProviderAdapter):
    """xAI 供应商适配器

    使用 xai_sdk.AsyncClient 而非 httpx2.AsyncClient，需要在 aclose 中显式关闭
    """

    provider_type: ClassVar[AIBuddyProviderType] = AIBuddyProviderType.xai
    settings_cls: ClassVar[type] = XaiModelSettings
    capabilities: ClassVar[ProviderCapabilities] = ProviderCapabilities(
        excluded_setting_fields=frozenset({'timeout', 'seed', 'logit_bias'}),
        supports_image_generation=False,
        image_supported_fields=None,
        extra_response_settings={},
    )

    def __init__(self) -> None:
        """初始化 xAI 供应商适配器"""
        self._clients: dict[int, AsyncClient] = {}

    def create_model(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        http_client: httpx2.AsyncClient,
    ) -> Model:
        """
        创建 xAI 模型实例（http_client 入参未使用，xAI 走自有 gRPC 客户端）

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        xai_client = self._build_xai_client(api_key=api_key, base_url=base_url)
        model = XaiModel(model_name, provider=XaiProvider(xai_client=xai_client))
        self._clients[id(model)] = xai_client
        return model

    def create_image_generation_model(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        http_client: httpx2.AsyncClient,
    ) -> ImageGenerationModel:
        """
        创建 xAI Grok Imagine 生图模型

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端，xAI 生图走 gRPC 不使用
        :return:
        """
        xai_client = self._build_xai_client(api_key=api_key, base_url=base_url)
        model = XaiImageGenerationModel(model_name, provider=XaiProvider(xai_client=xai_client))
        self._clients[id(model)] = xai_client
        return model

    @classmethod
    def _build_xai_client(cls, *, api_key: str, base_url: str) -> AsyncClient:
        """
        构建 xAI gRPC 客户端

        :param api_key: API 密钥
        :param base_url: API 基础地址
        :return:
        """
        base_url = normalize_provider_api_host(cls.provider_type, base_url)
        parsed_url = urlsplit(base_url)
        return AsyncClient(
            api_key=api_key,
            api_host=parsed_url.netloc,
            use_insecure_channel=parsed_url.scheme == 'http',
        )

    @classmethod
    async def list_models(cls, *, api_key: str, api_host: str) -> list[ProviderModelSnapshot]:
        """
        获取 xAI 模型列表

        :param api_key: 接口密钥
        :param api_host: 接口地址
        :return:
        """
        return await list_openai_compat_models(provider_type=cls.provider_type, api_key=api_key, api_host=api_host)

    async def aclose(self, model: object) -> None:
        """
        关闭 xAI 客户端

        :param model: 模型实例
        :return:
        """
        client = self._clients.pop(id(model), None)
        if client is None:
            return
        close = getattr(client, 'close', None)
        if close is None:
            return
        result = close()
        if isawaitable(result):
            await result
