from typing import ClassVar

import httpx2

from pydantic_ai.images import ImageGenerationModel
from pydantic_ai.images.google import GoogleImageGenerationModel
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.providers.google import GoogleProvider

from backend.plugin.ai_buddy.enums import AIBuddyProviderType
from backend.plugin.ai_buddy.provider.base import ProviderAdapter, ProviderCapabilities, normalize_provider_api_host


class GoogleAdapter(ProviderAdapter):
    """Google 供应商适配器"""

    provider_type: ClassVar[AIBuddyProviderType] = AIBuddyProviderType.google
    settings_cls: ClassVar[type] = GoogleModelSettings
    capabilities: ClassVar[ProviderCapabilities] = ProviderCapabilities(
        excluded_setting_fields=frozenset({'parallel_tool_calls', 'logit_bias'}),
        supports_image_generation=False,
        image_supported_fields=None,
        extra_response_settings={},
    )

    @classmethod
    def create_model(
        cls,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        http_client: httpx2.AsyncClient,
    ) -> Model:
        """
        创建 Google 模型实例

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        return GoogleModel(
            model_name,
            provider=cls._create_provider(api_key=api_key, base_url=base_url, http_client=http_client),
        )

    @classmethod
    def create_image_generation_model(
        cls,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        http_client: httpx2.AsyncClient,
    ) -> ImageGenerationModel:
        """
        创建 Google 独立生图模型

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        return GoogleImageGenerationModel(
            model_name,
            provider=cls._create_provider(api_key=api_key, base_url=base_url, http_client=http_client),
        )

    @classmethod
    def _create_provider(
        cls,
        *,
        api_key: str,
        base_url: str,
        http_client: httpx2.AsyncClient,
    ) -> GoogleProvider:
        """
        构建 Google Provider

        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        # google-genai 会自行追加 API 版本号，传入的地址不能再带 /v1beta
        host = normalize_provider_api_host(cls.provider_type, base_url).removesuffix('/v1beta')
        return GoogleProvider(
            base_url=host,
            api_key=api_key,
            http_client=http_client,
        )
