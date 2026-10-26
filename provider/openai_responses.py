from typing import Any, ClassVar

import httpx2

from openai import AsyncOpenAI
from pydantic_ai.images import ImageGenerationModel
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from backend.plugin.ai_buddy.enums import AIBuddyProviderType, AIBuddyWebSearchType
from backend.plugin.ai_buddy.provider.base import (
    ProviderAdapter,
    ProviderCapabilities,
    ProviderModelSnapshot,
    normalize_provider_api_host,
)
from backend.plugin.ai_buddy.provider.openai_image import OpenAICompatibleImageGenerationModel
from backend.plugin.ai_buddy.provider.seedream import SeedreamImageGenerationModel, is_seedream_model
from backend.plugin.ai_buddy.schema.chat import AIBuddyForwardedPropsParam
from backend.plugin.ai_buddy.utils.model_listing import list_openai_compat_models


class OpenAIResponsesAdapter(ProviderAdapter):
    """OpenAI Responses 供应商适配器"""

    provider_type: ClassVar[AIBuddyProviderType] = AIBuddyProviderType.openai_responses
    settings_cls: ClassVar[type] = OpenAIResponsesModelSettings
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
        创建 OpenAI Responses 模型实例

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        return OpenAIResponsesModel(
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
        创建 OpenAI Images API 或 Seedream 生图模型

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        image_model_cls = (
            SeedreamImageGenerationModel if is_seedream_model(model_name) else OpenAICompatibleImageGenerationModel
        )
        return image_model_cls(
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
    ) -> OpenAIProvider:
        """
        构建 OpenAI Provider

        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        return OpenAIProvider(
            openai_client=AsyncOpenAI(
                base_url=normalize_provider_api_host(cls.provider_type, base_url),
                api_key=api_key,
                max_retries=0,
                http_client=http_client,
            )
        )

    @classmethod
    async def list_models(cls, *, api_key: str, api_host: str) -> list[ProviderModelSnapshot]:
        """
        获取 OpenAI Responses 模型列表

        :param api_key: 接口密钥
        :param api_host: 接口地址
        :return:
        """
        return await list_openai_compat_models(provider_type=cls.provider_type, api_key=api_key, api_host=api_host)

    @staticmethod
    def resolve_extra_settings(
        *,
        forwarded_props: AIBuddyForwardedPropsParam,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        """
        根据请求附加 Responses 专属 settings

        :param forwarded_props: 聊天扩展参数
        :param model_name: 模型名称
        :return:
        """
        extras: dict[str, Any] = {}
        if getattr(forwarded_props, 'web_search', None) == AIBuddyWebSearchType.builtin:
            extras['openai_include_web_search_sources'] = True
        return extras
