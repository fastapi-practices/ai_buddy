from datetime import datetime

from pydantic import ConfigDict, Field, field_serializer, field_validator, model_validator

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import (
    MODEL_INPUT_MODALITIES,
    AIBuddyChatThinkingType,
    AIBuddyModelCapability,
    AIBuddyModelKind,
    AIBuddyModelModality,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.utils.sensitive_data import mask_api_key


class AIBuddyModelAllQueryParam(SchemaBase):
    """AI 模型全集查询参数"""

    provider_id: int = Field(description='供应商 ID')
    kind: AIBuddyModelKind | None = Field(None, description='模型类型')
    capability: AIBuddyModelCapability | None = Field(None, description='模型能力')


class AIBuddyModelQueryParam(SchemaBase):
    """AI 模型查询参数"""

    provider_id: int | None = Field(None, description='供应商 ID')
    model_id: str | None = Field(None, description='模型 ID')
    status: int | None = Field(None, description='状态')
    kind: AIBuddyModelKind | None = Field(None, description='模型类型')
    capability: AIBuddyModelCapability | None = Field(None, description='模型能力')


class AIBuddyThinkingPolicy(SchemaBase):
    """模型级可选择思考强度；空值表示没有可调节档位"""

    model_config = ConfigDict(extra='forbid')

    levels: list[AIBuddyChatThinkingType] = Field(default_factory=list, description='可选择的思考档位')
    default_level: AIBuddyChatThinkingType | None = Field(
        None, description='请求未指定时采用的档位；空值沿用供应商默认'
    )
    can_disable: bool = Field(False, description='是否允许显式关闭思考')

    @model_validator(mode='after')
    def validate_policy(self) -> 'AIBuddyThinkingPolicy':
        """校验思考档位唯一性和默认档位归属"""
        if AIBuddyChatThinkingType.off in self.levels:
            raise ValueError('off 不是思考档位，请使用 can_disable')
        if len(set(self.levels)) != len(self.levels):
            raise ValueError('思考档位不可重复')
        if self.default_level is not None and self.default_level not in self.levels:
            raise ValueError('默认思考档位必须包含在支持的档位中')
        return self


def validate_input_modalities(kind: AIBuddyModelKind, modalities: list[AIBuddyModelModality] | None) -> None:
    """
    校验输入模态与模型类型是否匹配

    :param kind: 模型类型
    :param modalities: 输入模态，空值表示未知
    :return:
    """
    if modalities is None:
        return
    if AIBuddyModelModality.text not in modalities:
        raise ValueError('当前模型类型需要支持文本输入')
    if not set(modalities) <= MODEL_INPUT_MODALITIES[kind]:
        raise ValueError('当前模型类型不支持所选输入模态')


class AIBuddyModelSchemaBase(SchemaBase):
    """AI 模型基础模型"""

    provider_id: int = Field(description='供应商 ID')
    model_id: str = Field(description='模型 ID')
    name: str | None = Field(None, max_length=256, description='模型名称')
    kind: AIBuddyModelKind = Field(description='模型类型')
    capabilities: list[AIBuddyModelCapability] = Field(default_factory=list, description='模型行为能力')
    input_modalities: list[AIBuddyModelModality] | None = Field(None, description='模型输入模态；空值表示未知')
    thinking_policy: AIBuddyThinkingPolicy | None = Field(None, description='可选择的思考档位；空值表示不可调节')
    context_window: int | None = Field(None, ge=1, description='上下文窗口 token 数')
    max_output_tokens: int | None = Field(None, ge=1, description='最大输出 token 数')
    sort: int = Field(default=0, description='排序')
    status: StatusType = Field(description='状态')
    remark: str | None = Field(None, description='备注')

    @field_validator('capabilities', mode='before')
    @classmethod
    def default_capabilities(cls, value: list[str] | None) -> list[str]:
        """
        未提供能力时默认为空

        :param value: 待处理值
        :return:
        """
        return [] if value is None else value

    @model_validator(mode='after')
    def validate_thinking_policy(self) -> 'AIBuddyModelSchemaBase':
        """校验输入模态、模型行为能力和思考策略"""
        validate_input_modalities(self.kind, self.input_modalities)
        if self.kind != AIBuddyModelKind.chat and self.capabilities:
            raise ValueError('仅对话模型支持工具和思考能力')
        if self.thinking_policy is not None and (
            self.kind != AIBuddyModelKind.chat or AIBuddyModelCapability.thinking not in self.capabilities
        ):
            raise ValueError('思考策略仅适用于启用思考能力的对话模型')
        return self


class CreateAIBuddyModelParam(AIBuddyModelSchemaBase):
    """创建 AI 模型参数"""


class CreateMyAIBuddyModelParam(AIBuddyModelSchemaBase):
    """客户端创建模型参数"""

    status: StatusType = Field(default=StatusType.enable, description='状态')


class UpdateAIBuddyModelParam(AIBuddyModelSchemaBase):
    """更新 AI 模型参数"""


class UpdateMyAIBuddyModelParam(CreateMyAIBuddyModelParam):
    """客户端更新模型参数"""


class CreateAIBuddyModelsParam(SchemaBase):
    """批量创建 AI 模型参数"""

    items: list[CreateAIBuddyModelParam] = Field(max_length=200, description='模型列表')


class DeleteAIBuddyModelParam(SchemaBase):
    """删除 AI 模型参数"""

    pks: list[int] = Field(description='模型 ID 列表')


class GetAIBuddyModelDetail(AIBuddyModelSchemaBase):
    """AI 模型详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='模型 ID')
    name: str = Field(description='模型名称')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class GetMyAIBuddyModelDetail(AIBuddyModelSchemaBase):
    """客户端模型详情"""

    id: int = Field(description='模型 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
    type: AIBuddyProviderType = Field(description='供应商类型')
    api_key: str = Field(description='接口密钥')
    api_host: str = Field(description='接口地址')
    user_id: int = Field(description='用户 ID')

    @field_serializer('api_key')
    @staticmethod
    def serialize_api_key(api_key: str) -> str:
        """
        脱敏返回接口密钥

        :param api_key: 接口密钥
        :return:
        """
        return mask_api_key(api_key)
