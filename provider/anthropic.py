from typing import ClassVar

import httpx2

from anthropic import AsyncAnthropic
from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider

from backend.plugin.ai_buddy.enums import AIBuddyProviderType
from backend.plugin.ai_buddy.provider.base import ProviderAdapter, ProviderCapabilities, normalize_provider_api_host


class AnthropicAdapter(ProviderAdapter):
    """Anthropic 供应商适配器"""

    provider_type: ClassVar[AIBuddyProviderType] = AIBuddyProviderType.anthropic
    settings_cls: ClassVar[type] = AnthropicModelSettings
    capabilities: ClassVar[ProviderCapabilities] = ProviderCapabilities(
        excluded_setting_fields=frozenset({'seed', 'presence_penalty', 'frequency_penalty', 'logit_bias'}),
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
        创建 Anthropic 模型实例

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        base_url = normalize_provider_api_host(cls.provider_type, base_url)
        anthropic_client = AsyncAnthropic(
            base_url=base_url,
            api_key=api_key,
            max_retries=0,
            http_client=http_client,
        )
        return AnthropicModel(
            model_name,
            provider=AnthropicProvider(anthropic_client=anthropic_client),
        )
