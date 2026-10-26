from typing import Any, ClassVar

from pydantic_ai import DeferredToolRequests

from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.work.generation.base import GenerationHandler
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType, AIBuddyModelKind, AIBuddyProviderType


class TextGenerationHandler(GenerationHandler):
    """文本生成模式处理器"""

    generation_type: ClassVar[AIBuddyChatGenerationType] = AIBuddyChatGenerationType.text

    @staticmethod
    def validate_model(
        *,
        provider_type: int | AIBuddyProviderType,
        model_name: str,
        kind: AIBuddyModelKind,
    ) -> None:
        """
        校验对话只能使用对话模型

        :param provider_type: 供应商类型
        :param model_name: 模型名称
        :param kind: 模型类型
        :return:
        """
        if kind == AIBuddyModelKind.image:
            raise errors.RequestError(msg='当前模型仅用于图片生成，请更换对话模型')
        if kind != AIBuddyModelKind.chat:
            raise errors.RequestError(msg='当前模型不是对话模型，请更换对话模型')

    @staticmethod
    def get_output_type() -> Any:
        """获取文本生成输出类型"""
        return [str, DeferredToolRequests]
