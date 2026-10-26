from pydantic import ConfigDict, Field

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyModelKind, AIBuddyProviderType
from backend.plugin.ai_buddy.schema.default_model import GetAIBuddyDefaultModelDetail
from backend.plugin.ai_buddy.schema.model import GetAIBuddyModelDetail


class GetAIBuddyProviderModelOptionDetail(SchemaBase):
    """AI 供应商模型选项详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='供应商 ID')
    user_id: int = Field(description='用户 ID')
    name: str = Field(description='供应商名称')
    type: AIBuddyProviderType = Field(description='供应商类型')
    status: StatusType = Field(description='状态')
    models: list[GetAIBuddyModelDetail] = Field(description='启用的模型列表')


class GetAIBuddyModelOptionDetail(SchemaBase):
    """AI 模型选项详情"""

    providers: list[GetAIBuddyProviderModelOptionDetail] = Field(description='启用的供应商及模型列表')
    default_candidates: dict[AIBuddyModelKind, list[int]] = Field(description='各默认用途可选的平台模型 ID')
    default_models: dict[AIBuddyModelKind, GetAIBuddyDefaultModelDetail | None] = Field(
        description='按模型类型划分的默认模型'
    )
