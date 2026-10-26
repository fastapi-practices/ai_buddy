from typing import Literal, Self

from pydantic import Field, model_validator

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyExecutionBackend, AIBuddyTestReportArchiveStatus
from backend.plugin.ai_buddy.schema.command import AIBuddyCommandResult


class AIBuddyTestReportArchive(SchemaBase):
    """报告保存结果"""

    status: AIBuddyTestReportArchiveStatus = Field(description='归档状态')
    artifact_id: str | None = Field(pattern=r'^[1-9][0-9]*$', description='已提交产物的十进制 ID，失败时为 null')
    error: str | None = Field(description='归档失败原因')

    @model_validator(mode='after')
    def validate_archive(self) -> Self:
        """已保存报告必须有产物引用，失败报告必须有错误说明"""
        if self.status == AIBuddyTestReportArchiveStatus.saved and (self.artifact_id is None or self.error is not None):
            raise ValueError('已保存报告必须包含产物 ID 且无归档错误')
        if self.status == AIBuddyTestReportArchiveStatus.failed and (self.artifact_id is not None or not self.error):
            raise ValueError('归档失败必须包含错误且不能有产物 ID')
        return self


class GetAIBuddyTestReportDetail(SchemaBase):
    """测试命令事实与报告产物的关联"""

    kind: Literal['test_report'] = Field('test_report', description='工具结果类型')
    schema_version: Literal[1] = Field(1, description='报告协议版本')
    conversation_id: str = Field(description='所属对话 ID')
    run_id: str = Field(description='真实编码运行 ID')
    workspace_id: str | None = Field(description='所属工作区 ID')
    execution_backend: AIBuddyExecutionBackend = Field(description='实际执行后端')
    requested_command: str = Field(description='模型或用户显式提供的原始命令')
    execution: AIBuddyCommandResult = Field(description='执行事实')
    archive: AIBuddyTestReportArchive = Field(description='可下载报告的归档结果')
    preview_truncated: bool = Field(False, description='聊天工具结果中的输出预览是否被单独截断')
