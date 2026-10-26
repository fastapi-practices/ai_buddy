from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyModelKind, AIBuddyProviderType


class AIBuddyDefaultModelSchemaBase(SchemaBase):
    """AI 默认模型基础模型"""

    provider_id: int = Field(description='供应商 ID')
    model_id: str = Field(description='模型 ID')
    status: StatusType = Field(description='状态')


class UpdateAIBuddyDefaultModelParam(AIBuddyDefaultModelSchemaBase):
    """更新 AI 默认模型参数"""


class GetAIBuddyDefaultModelDetail(SchemaBase):
    """AI 默认模型详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='默认模型 ID')
    kind: AIBuddyModelKind = Field(description='模型类型')
    provider_id: int = Field(description='供应商 ID')
    provider_name: str = Field(description='供应商名称')
    provider_type: AIBuddyProviderType = Field(description='供应商类型')
    model_id: str = Field(description='模型 ID')
    status: StatusType = Field(description='状态')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
