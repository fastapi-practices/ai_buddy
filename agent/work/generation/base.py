from abc import ABC, abstractmethod
from typing import Any, ClassVar

from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType, AIBuddyModelKind, AIBuddyProviderType


class GenerationHandler(ABC):
    """生成模式处理器"""

    generation_type: ClassVar[AIBuddyChatGenerationType]

    @staticmethod
    def validate_provider_type(provider_type: int | AIBuddyProviderType) -> None:
        """
        校验供应商是否支持当前生成模式

        :param provider_type: 供应商类型
        :return:
        """
        return

    @staticmethod
    def validate_model(
        *,
        provider_type: int | AIBuddyProviderType,
        model_name: str,
        kind: AIBuddyModelKind,
    ) -> None:
        """
        校验模型是否支持当前生成模式

        :param provider_type: 供应商类型
        :param model_name: 模型名称
        :param kind: 模型类型
        :return:
        """
        return

    @staticmethod
    @abstractmethod
    def get_output_type() -> Any:
        """获取 Agent 输出类型"""
