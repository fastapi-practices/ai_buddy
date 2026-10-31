from datetime import datetime, timedelta
from typing import Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyCommandReason

COMMAND_MAX_BYTES = 64 * 1024
COMMAND_OUTPUT_MAX_BYTES = 512 * 1024


class AIBuddyCommandParam(SchemaBase):
    """显式提供的受控命令"""

    model_config = ConfigDict(extra='forbid', strict=True)

    command: str = Field(description='实际请求执行的 shell 命令')

    @field_validator('command')
    @classmethod
    def validate_command(cls, value: str) -> str:
        """
        保留原始命令并拒绝空值、空字符及超限输入

        :param value: 待校验的命令
        :return:
        """
        if not value.strip() or '\0' in value or len(value.encode()) > COMMAND_MAX_BYTES:
            raise ValueError('命令不能为空、包含空字符或超过 64 KiB')
        return value


class AIBuddyCommandResult(AIBuddyCommandParam):
    """执行器返回的命令事实结果，不从输出文本推测状态"""

    exit_code: int | None = Field(description='进程实际退出码，无法获取时为 null')
    stdout: str = Field(description='保留的标准输出')
    stderr: str = Field(description='保留的标准错误输出')
    reason: AIBuddyCommandReason = Field(strict=False, description='执行完成或中止的原因')
    started_at: str | None = Field(description='执行器开始调用的 ISO UTC 时间，未知时为 null')
    duration_ms: int | None = Field(description='执行器观测的运行时长，未知时为 null')
    truncated: bool = Field(description='输出是否被裁剪')
    output_complete: bool = Field(description='是否收到正常完成的完整输出')
    result_available: bool = Field(description='是否取得执行器的最终结果')

    @field_validator('started_at')
    @classmethod
    def validate_started_at(cls, value: str | None) -> str | None:
        """
        开始时间必须是带 UTC 偏移的有效 ISO 时间

        :param value: 待校验的开始时间
        :return:
        """
        if value is None:
            return None
        parsed = datetime.fromisoformat(value)
        if parsed.utcoffset() != timedelta(0):
            raise ValueError('开始时间必须使用 ISO UTC 时间')
        return parsed.isoformat()

    @model_validator(mode='after')
    def validate_result(self) -> Self:
        """拒绝互相矛盾或超限的执行事实"""
        if len(self.stdout.encode()) + len(self.stderr.encode()) > COMMAND_OUTPUT_MAX_BYTES:
            raise ValueError('命令输出超过 512 KiB')
        if self.output_complete != (self.reason == AIBuddyCommandReason.completed) or (
            self.truncated and self.output_complete
        ):
            raise ValueError('命令输出完整性与终止原因不一致')
        if self.reason == AIBuddyCommandReason.completed and (self.exit_code is None or not self.result_available):
            raise ValueError('完成的命令必须提供真实退出码和执行结果')
        if not self.result_available and self.exit_code is not None:
            raise ValueError('缺失执行结果时不能提供退出码')
        return self


class AIBuddyBackgroundTaskDetail(SchemaBase):
    """后台命令任务状态与增量日志"""

    task_id: str = Field(description='后台命令任务 ID')
    running: bool = Field(description='任务是否仍在运行')
    exit_code: int | None = Field(description='任务结束后的退出码，运行中或未知时为 null')
    error: str | None = Field(description='任务失败原因')
    started_at: datetime | None = Field(description='任务开始时间')
    finished_at: datetime | None = Field(description='任务结束时间')
    logs: str = Field(description='自上次游标以来的新输出')
    cursor: int | None = Field(description='下次增量读取使用的游标')
