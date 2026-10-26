from typing import ClassVar

import httpx2

from openai import AsyncOpenAI
from pydantic_ai.models import Model
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.providers.openrouter import OpenRouterProvider

from backend.common.exception import errors
from backend.plugin.ai_buddy.enums import AIBuddyProviderType
from backend.plugin.ai_buddy.provider.base import (
    ProviderAdapter,
    ProviderCapabilities,
    ProviderModelSnapshot,
    normalize_provider_api_host,
)
from backend.plugin.ai_buddy.utils.model_listing import list_openai_compat_models


class OpenRouterAdapter(ProviderAdapter):
    """OpenRouter 供应商适配器"""

    provider_type: ClassVar[AIBuddyProviderType] = AIBuddyProviderType.openrouter
    settings_cls: ClassVar[type] = OpenRouterModelSettings
    capabilities: ClassVar[ProviderCapabilities] = ProviderCapabilities(
        excluded_setting_fields=frozenset(),
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
        创建 OpenRouter 模型实例

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        base_url = normalize_provider_api_host(cls.provider_type, base_url)
        if base_url:
            provider = OpenRouterProvider(
                openai_client=AsyncOpenAI(
                    base_url=base_url,
                    api_key=api_key,
                    max_retries=0,
                    http_client=http_client,
                ),
            )
        else:
            provider = OpenRouterProvider(api_key=api_key, http_client=http_client)
        return OpenRouterModel(model_name, provider=provider)

    @staticmethod
    def validate_model_id(model_id: str) -> None:
        """
        校验 OpenRouter 模型 ID 必须包含供应商前缀

        :param model_id: 模型 ID
        :return:
        """
        if '/' not in model_id:
            raise errors.RequestError(msg='OpenRouter 模型 ID 必须包含供应商前缀，例如 openai/gpt-4o-mini')

    @classmethod
    async def list_models(cls, *, api_key: str, api_host: str) -> list[ProviderModelSnapshot]:
        """
        获取 OpenRouter 模型列表

        :param api_key: 接口密钥
        :param api_host: 接口地址
        :return:
        """
        return await list_openai_compat_models(provider_type=cls.provider_type, api_key=api_key, api_host=api_host)
