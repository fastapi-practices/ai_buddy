from typing import Any, ClassVar

from pydantic_ai import BinaryImage

from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.work.generation.base import GenerationHandler
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType, AIBuddyModelKind, AIBuddyProviderType

_IMAGE_PROVIDERS: frozenset[AIBuddyProviderType] = frozenset({
    AIBuddyProviderType.google,
    AIBuddyProviderType.openai,
    AIBuddyProviderType.openai_responses,
    AIBuddyProviderType.xai,
})
_DEDICATED_IMAGE_HINTS: dict[AIBuddyProviderType, str] = {
    AIBuddyProviderType.google: 'Google 生图请使用图片模型，例如 gemini-3-pro-image',
    AIBuddyProviderType.openai: 'OpenAI 兼容生图请使用图片模型，例如 gpt-image-2 或 doubao-seedream-*',
    AIBuddyProviderType.openai_responses: 'OpenAI 兼容生图请使用图片模型，例如 gpt-image-2 或 doubao-seedream-*',
    AIBuddyProviderType.xai: 'xAI 生图请使用 Imagine 图片模型，例如 grok-imagine-image',
}


class ImageGenerationHandler(GenerationHandler):
    """图片生成模式处理器

    只接受专用生图模型作为 model_id，一律走 ImageGenerator
    """

    generation_type: ClassVar[AIBuddyChatGenerationType] = AIBuddyChatGenerationType.image

    @staticmethod
    def validate_provider_type(provider_type: int | AIBuddyProviderType) -> None:
        """
        校验图片生成供应商

        :param provider_type: 供应商类型
        :return:
        """
        if AIBuddyProviderType(provider_type) not in _IMAGE_PROVIDERS:
            raise errors.RequestError(msg='当前图片生成仅支持 Google、OpenAI、OpenAI Responses 或 xAI 供应商')

    @staticmethod
    def validate_model(
        *,
        provider_type: int | AIBuddyProviderType,
        model_name: str,
        kind: AIBuddyModelKind,
    ) -> None:
        """
        校验必须使用图片模型

        :param provider_type: 供应商类型
        :param model_name: 模型名称
        :param kind: 模型类型
        :return:
        """
        provider = AIBuddyProviderType(provider_type)
        if kind != AIBuddyModelKind.image:
            raise errors.RequestError(msg=_DEDICATED_IMAGE_HINTS[provider])

    @staticmethod
    def get_output_type() -> Any:
        """获取图片生成输出类型"""
        return BinaryImage
