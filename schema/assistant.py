from datetime import datetime
from typing import Annotated

from pydantic import ConfigDict, Field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyAssistantCategory, AIBuddyAssistantSortType


class AIBuddyAssistantSortQueryParam(SchemaBase):
    """AI 助手排序查询参数"""

    sort_type: AIBuddyAssistantSortType = Field(
        AIBuddyAssistantSortType.newest,
        description='排序方式',
    )


class AIBuddyAssistantQueryParam(SchemaBase):
    """AI 助手查询参数"""

    name: str | None = Field(None, description='助手名称')
    category: AIBuddyAssistantCategory | None = Field(None, description='助手分类编码')
    sort_type: AIBuddyAssistantSortType = Field(
        AIBuddyAssistantSortType.newest,
        description='排序方式',
    )


class AIBuddyAssistantSchemaBase(SchemaBase):
    """AI 助手基础模型"""

    name: str = Field(max_length=64, description='助手名称')
    prompt: str = Field(description='角色提示词')
    description: str | None = Field(None, max_length=512, description='助手描述')
    category: AIBuddyAssistantCategory | None = Field(None, description='助手分类编码')
    starters: list[Annotated[str, Field(max_length=256)]] = Field(
        default_factory=list,
        max_length=8,
        description='开场白列表',
    )
    sort: int = Field(default=0, description='排序')

    @field_validator('starters', mode='before')
    @classmethod
    def default_starters(cls, value: list[str] | None) -> list[str]:
        """
        空值按空列表处理

        :param value: 待处理值
        :return:
        """
        return value or []


class CreateAIBuddyAssistantParam(AIBuddyAssistantSchemaBase):
    """创建 AI 助手参数"""


class UpdateAIBuddyAssistantParam(AIBuddyAssistantSchemaBase):
    """更新 AI 助手参数"""


class GetAIBuddyAssistantDetail(AIBuddyAssistantSchemaBase):
    """AI 助手详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='助手 ID')
    user_id: int = Field(description='用户 ID')
    usage_count: int = Field(default=0, description='使用次数')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class GetAIBuddyAssistantCategoryDetail(SchemaBase):
    """AI 助手分类"""

    code: AIBuddyAssistantCategory = Field(description='分类编码')
    name: str = Field(description='分类名称')
    sort: int = Field(description='排序')
