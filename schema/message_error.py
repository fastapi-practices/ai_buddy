from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class AIBuddyMessageErrorSchemaBase(SchemaBase):
    """AI 消息错误基础模型"""

    message_id: int = Field(description='消息 ID')
    conversation_id: str = Field(description='对话 ID')
    message: str = Field(description='错误信息')
    detail: dict[str, Any] | None = Field(None, description='错误详情')


class CreateAIBuddyMessageErrorParam(AIBuddyMessageErrorSchemaBase):
    """创建 AI 消息错误参数"""


class GetAIBuddyMessageErrorDetail(AIBuddyMessageErrorSchemaBase):
    """AI 消息错误详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='错误 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
