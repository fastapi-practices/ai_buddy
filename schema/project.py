from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class AIBuddyProjectSchemaBase(SchemaBase):
    """AI 项目基础模型"""

    model_config = ConfigDict(extra='forbid')

    name: str = Field(description='项目名称')
    sort: int = Field(default=0, description='排序')
    archived: bool = Field(default=False, description='是否归档')


class CreateAIBuddyProjectParam(AIBuddyProjectSchemaBase):
    """创建 AI 项目参数"""


class UpdateAIBuddyProjectParam(AIBuddyProjectSchemaBase):
    """更新 AI 项目参数"""


class GetAIBuddyProjectDetail(AIBuddyProjectSchemaBase):
    """AI 项目详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='项目 ID')
    user_id: int = Field(description='用户 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
