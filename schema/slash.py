from typing import Any

from pydantic import Field

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddySlashEntry


class AIBuddySlashQueryParam(SchemaBase):
    """AI 斜杠指令查询参数"""

    origin: AIBuddySlashEntry = Field(default=AIBuddySlashEntry.web, description='入口')


class GetAIBuddySlashCommandDetail(SchemaBase):
    """斜杠指令目录项"""

    name: str = Field(description='指令名')
    description: str = Field(description='指令说明')
    entries: list[AIBuddySlashEntry] = Field(description='可用入口')


class CreateAIBuddySlashParam(SchemaBase):
    """执行斜杠指令参数"""

    command: str = Field(description='指令名，不含前导斜杠')
    conversation_id: str | None = Field(None, description='当前对话 ID')
    args: str | None = Field(None, description='指令参数')
    origin: AIBuddySlashEntry = Field(default=AIBuddySlashEntry.web, description='入口')
    draft: str | None = Field(None, description='输入框草稿，仅 /polish 使用')


class GetAIBuddySlashResultDetail(SchemaBase):
    """斜杠指令执行结果"""

    command: str = Field(description='指令名')
    message: str = Field(description='执行结果说明')
    data: dict[str, Any] | None = Field(None, description='附加数据')
