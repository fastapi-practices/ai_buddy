from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class AIBuddySubagentQueryParam(SchemaBase):
    """AI 子代理查询参数"""

    name: str | None = Field(None, description='子代理名称')


class AIBuddySubagentSchemaBase(SchemaBase):
    """AI 子代理基础模型"""

    name: str = Field(description='子代理名称')
    description: str = Field(description='子代理描述')
    prompt: str = Field(description='角色提示词')
    sort: int = Field(default=0, description='排序')


class CreateAIBuddySubagentParam(AIBuddySubagentSchemaBase):
    """创建 AI 子代理参数"""


class UpdateAIBuddySubagentParam(AIBuddySubagentSchemaBase):
    """更新 AI 子代理参数"""


class GetAIBuddySubagentDetail(AIBuddySubagentSchemaBase):
    """AI 子代理详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='子代理 ID')
    user_id: int = Field(description='用户 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
