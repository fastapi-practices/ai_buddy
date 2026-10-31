from datetime import datetime

from pydantic import ConfigDict, Field, field_validator

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase


class AIBuddyCronSchemaBase(SchemaBase):
    """AI 定时任务基础模型"""

    name: str | None = Field(None, description='任务名称')
    conversation_id: str = Field(description='对话 ID')
    trigger: str = Field(description='调度表达式')
    prompt: str = Field(description='提示词')
    fresh_thread: bool = Field(default=False, description='每次执行是否新开对话')
    provider_id: int | None = Field(None, description='覆盖供应商 ID')
    model_id: str | None = Field(None, description='覆盖模型 ID')
    mcp_ids: list[int] = Field(default_factory=list, description='本轮 MCP ID 列表')
    status: StatusType = Field(default=StatusType.enable, description='状态')

    @field_validator('mcp_ids', mode='before')
    @classmethod
    def default_mcp_ids(cls, value: list[int] | None) -> list[int]:
        """
        空值按空列表处理

        :param value: 待处理值
        :return:
        """
        return value or []


class CreateAIBuddyCronParam(AIBuddyCronSchemaBase):
    """创建 AI 定时任务参数"""


class UpdateAIBuddyCronParam(AIBuddyCronSchemaBase):
    """更新 AI 定时任务参数"""


class GetAIBuddyCronDetail(AIBuddyCronSchemaBase):
    """AI 定时任务详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='任务 ID')
    name: str = Field(description='任务名称')
    user_id: int = Field(description='用户 ID')
    last_run_time: datetime | None = Field(None, description='最近执行时间')
    last_status: str | None = Field(None, description='最近执行状态')
    last_error: str | None = Field(None, description='最近执行错误')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
