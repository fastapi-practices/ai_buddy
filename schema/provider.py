from datetime import datetime

from pydantic import ConfigDict, Field, field_serializer

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import (
    AIBuddyModelCapability,
    AIBuddyModelKind,
    AIBuddyModelModality,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.utils.sensitive_data import mask_api_key


class AIBuddyProviderQueryParam(SchemaBase):
    """AI 供应商查询参数"""

    name: str | None = Field(None, description='供应商名称')
    type: int | None = Field(None, description='供应商类型')
    status: int | None = Field(None, description='状态')


class AIBuddyProviderSchemaBase(SchemaBase):
    """AI 供应商基础模型"""

    name: str = Field(description='供应商名称')
    type: AIBuddyProviderType = Field(description='供应商类型')
    api_key: str = Field(description='接口密钥')
    api_host: str = Field(description='接口地址')
    status: StatusType = Field(description='状态')
    remark: str | None = Field(None, description='备注')


class CreateAIBuddyProviderParam(AIBuddyProviderSchemaBase):
    """创建 AI 供应商参数"""


class UpdateAIBuddyProviderParam(AIBuddyProviderSchemaBase):
    """更新 AI 供应商参数"""


class CreateMyAIBuddyProviderParam(SchemaBase):
    """客户端创建 AI 供应商参数"""

    name: str = Field(description='供应商名称')
    type: AIBuddyProviderType = Field(description='供应商类型')
    api_key: str = Field(description='接口密钥')
    api_host: str | None = Field(None, description='接口地址，空则使用该类型默认地址')
    status: StatusType = Field(default=StatusType.enable, description='状态')
    remark: str | None = Field(None, description='备注')


class UpdateMyAIBuddyProviderParam(CreateMyAIBuddyProviderParam):
    """客户端更新 AI 供应商参数"""


class DeleteAIBuddyProviderParam(SchemaBase):
    """删除 AI 供应商参数"""

    pks: list[int] = Field(description='供应商 ID 列表')


class GetAIBuddyProviderDetail(AIBuddyProviderSchemaBase):
    """AI 供应商详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='供应商 ID')
    user_id: int = Field(description='用户 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @field_serializer('api_key')
    @staticmethod
    def serialize_api_key(api_key: str) -> str:
        """
        脱敏返回接口密钥

        :param api_key: 接口密钥
        :return:
        """
        return mask_api_key(api_key)


class GetMyAIBuddyProviderDetail(GetAIBuddyProviderDetail):
    """客户端 AI 供应商详情"""


class GetAIBuddyProviderModelDetail(SchemaBase):
    """获取供应商模型详情"""

    id: str = Field(description='模型标识符')
    object: str | None = Field(None, description='模型对象类型')
    created: int | None = Field(None, description='模型创建时的 Unix 时间戳（以秒为单位）')
    display_name: str | None = Field(None, description='模型展示名称')
    kind: AIBuddyModelKind = Field(description='模型类型')
    capabilities: list[AIBuddyModelCapability] = Field(default_factory=list, description='模型行为能力')
    input_modalities: list[AIBuddyModelModality] = Field(default_factory=list, description='输入模态')
    context_window: int | None = Field(None, description='上下文窗口 token 数')
    max_output_tokens: int | None = Field(None, description='最大输出 token 数')
