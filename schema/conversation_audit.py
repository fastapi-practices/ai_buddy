from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyConversationAuditAction


class AIBuddyConversationAuditQueryParam(SchemaBase):
    """AI 会话审计查询参数"""

    conversation_id: str | None = Field(None, description='限定的对话 ID')
    before: int | None = Field(None, description='上一页最小审计 ID')
    limit: int = Field(50, description='返回条数')


class GetAIBuddyConversationAuditDetail(SchemaBase):
    """AI 会话审计详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='审计 ID')
    conversation_id: str = Field(description='对话 ID')
    action: AIBuddyConversationAuditAction = Field(description='审计动作')
    client: str | None = Field(None, description='访问来源')
    detail: dict[str, str | int | None] | None = Field(None, description='审计详情')
    created_time: datetime = Field(description='发生时间')
