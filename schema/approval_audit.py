from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyApprovalStatus


class AIBuddyApprovalAuditQueryParam(SchemaBase):
    """AI 审批审计查询参数"""

    before: int | None = Field(None, description='上一页最小审计 ID')
    limit: int = Field(50, description='返回条数')


class GetAIBuddyApprovalAuditDetail(SchemaBase):
    """AI 工具审批审计详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='审计 ID')
    conversation_id: str = Field(description='对话 ID')
    request_id: str = Field(description='审批请求 ID')
    run_id: str = Field(description='运行 ID')
    tool_call_id: str = Field(description='工具调用 ID')
    tool_name: str = Field(description='工具名称')
    arguments_sha256: str = Field(description='原始参数摘要，不存储命令中的凭据')
    status: AIBuddyApprovalStatus = Field(description='审批状态')
    created_time: datetime = Field(description='发起时间')
    expires_time: datetime | None = Field(None, description='审批过期时间')
    resolved_time: datetime | None = Field(None, description='审批结束时间')
