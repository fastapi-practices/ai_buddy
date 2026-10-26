from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, TypedDict
from urllib.parse import urlsplit

import httpx2

from pydantic_ai import ModelSettings
from pydantic_ai.images import ImageGenerationModel
from pydantic_ai.models import Model

from backend.common.exception import errors
from backend.plugin.ai_buddy.enums import (
    AIBuddyModelCapability,
    AIBuddyModelKind,
    AIBuddyModelModality,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.schema.chat import AIBuddyForwardedPropsParam

COMMON_MODEL_SETTING_FIELDS: frozenset[str] = frozenset({
    'max_tokens',
    'temperature',
    'top_p',
    'timeout',
    'request_timeout',
    'parallel_tool_calls',
    'seed',
    'presence_penalty',
    'frequency_penalty',
    'logit_bias',
    'stop_sequences',
})


@dataclass(frozen=True, slots=True)
class ProviderModelSnapshot:
    """供应商返回的模型标识"""

    id: str
    object: str | None = None
    created: int | None = None
    display_name: str | None = None
    kind: AIBuddyModelKind = AIBuddyModelKind.chat
    capabilities: tuple[AIBuddyModelCapability, ...] = ()
    input_modalities: tuple[AIBuddyModelModality, ...] = (AIBuddyModelModality.text,)
    context_window: int | None = None
    max_output_tokens: int | None = None


class ProviderCapabilities(TypedDict):
    """供应商能力描述"""

    excluded_setting_fields: frozenset[str]
    supports_image_generation: bool
    image_supported_fields: frozenset[str] | None
    extra_response_settings: dict[str, bool]


class ProviderAdapter(ABC):
    """供应商适配器基类"""

    provider_type: ClassVar[AIBuddyProviderType]
    settings_cls: ClassVar[type[ModelSettings]]
    capabilities: ClassVar[ProviderCapabilities]

    @abstractmethod
    def create_model(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        http_client: httpx2.AsyncClient,
    ) -> Model:
        """
        创建供应商模型实例

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """

    @staticmethod
    def create_image_generation_model(
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        http_client: httpx2.AsyncClient,
    ) -> ImageGenerationModel:
        """
        创建独立生图模型实例

        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param http_client: 共享 HTTP 客户端
        :return:
        """
        raise errors.RequestError(msg='当前供应商暂不支持独立生图模型')

    @staticmethod
    async def aclose(model: object) -> None:
        """
        关闭供应商私有客户端，默认无需关闭

        :param model: 模型实例
        :return:
        """
        return

    @staticmethod
    def validate_model_id(model_id: str) -> None:
        """
        校验模型 ID 格式，默认无需校验

        :param model_id: 模型 ID
        :return:
        """
        return

    @staticmethod
    async def list_models(*, api_key: str, api_host: str) -> list[ProviderModelSnapshot]:
        """
        获取供应商远程模型列表，默认不支持自动同步

        :param api_key: 接口密钥
        :param api_host: 接口地址
        :return:
        """
        raise errors.RequestError(msg='当前供应商暂不支持自动同步模型，请手动维护模型列表')

    @staticmethod
    def resolve_extra_settings(
        *,
        forwarded_props: AIBuddyForwardedPropsParam,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        """
        获取供应商特有的额外 settings，默认无

        :param forwarded_props: 聊天扩展参数
        :param model_name: 模型名称
        :return:
        """
        return {}


def resolve_provider_api_host(provider_type: int | AIBuddyProviderType, api_host: str | None) -> str:
    """
    解析供应商接口地址，空值回落到该类型默认地址

    :param provider_type: 供应商类型
    :param api_host: API 地址
    :return:
    """
    try:
        resolved_type = AIBuddyProviderType(provider_type)
    except (TypeError, ValueError) as exc:
        raise errors.RequestError(msg=f'当前不支持此供应商: {provider_type}') from exc
    host = (api_host or '').strip() or resolved_type.default_api_host
    parsed = urlsplit(host)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise errors.RequestError(msg='接口地址必须是合法的 HTTP(S) 地址')
    return host.rstrip('/')


def normalize_provider_api_host(provider_type: int | AIBuddyProviderType, api_host: str) -> str:
    """
    标准化供应商 API 地址

    :param provider_type: 供应商类型
    :param api_host: API 地址
    :return:
    """
    try:
        resolved_type = AIBuddyProviderType(provider_type)
    except (TypeError, ValueError) as exc:
        raise errors.RequestError(msg=f'当前不支持此供应商: {provider_type}') from exc
    api_host = api_host.strip().rstrip('/')
    if not api_host:
        raise errors.RequestError(msg='供应商接口地址不能为空')
    if urlsplit(api_host).path.strip('/'):
        return api_host
    return api_host + resolved_type.default_api_path
