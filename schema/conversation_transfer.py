from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyConversationSource,
    AIBuddyConversationSurface,
    AIBuddyMessageRole,
    AIBuddyMessageStatus,
    AIBuddyOrigin,
)


class AIBuddyConversationTransferMessage(SchemaBase):
    """可迁移的会话消息，附件以内联 base64 携带，不依赖原部署的对象存储"""

    message_index: int = Field(description='会话内顺序号')
    role: AIBuddyMessageRole = Field(description='消息角色')
    origin: AIBuddyOrigin = Field(AIBuddyOrigin.web, description='消息来源')
    status: AIBuddyMessageStatus = Field(AIBuddyMessageStatus.success, description='消息状态，不允许 pending')
    model_messages: list[dict[str, Any]] = Field(description='原始模型消息列表')
    turn_context: dict[str, Any] | None = Field(None, description='本轮实际组合')
    client_message_id: str | None = Field(None, description='客户端消息 ID')
    created_time: datetime | None = Field(None, description='原始创建时间，导入后仅保留在 turn_context 中')


class AIBuddyConversationTransferInfo(SchemaBase):
    """可迁移的会话信息，不含项目、助手等与具体部署绑定的关联"""

    conversation_id: str = Field(description='对话 ID，导入时若未被占用则保留')
    title: str = Field(description='对话标题')
    provider_id: int = Field(description='供应商 ID，导入用户必须可见')
    model_id: str = Field(description='模型 ID')
    agent_mode: AIBuddyAgentMode | None = Field(None, description='最近一轮使用的会话模式')
    goal: str | None = Field(None, description='对话目标')
    origin: AIBuddyOrigin = Field(AIBuddyOrigin.web, description='对话来源')
    surface: AIBuddyConversationSurface = Field(AIBuddyConversationSurface.chat, description='会话入口')
    source: AIBuddyConversationSource = Field(AIBuddyConversationSource.cloud, description='会话事实源，导入后原样保留')


class AIBuddyConversationTransfer(SchemaBase):
    """会话导出与导入的统一文档"""

    format: Literal['ai-buddy-conversation'] = Field(description='文档格式标识')
    version: Literal[1] = Field(description='文档版本')
    exported_time: datetime | None = Field(None, description='导出时间')
    conversation: AIBuddyConversationTransferInfo = Field(description='会话信息')
    messages: list[AIBuddyConversationTransferMessage] = Field(description='按顺序号升序排列的消息')


class GetAIBuddyConversationImportDetail(SchemaBase):
    """会话导入结果"""

    conversation_id: str = Field(description='导入后的对话 ID')
    id_kept: bool = Field(description='是否保留了文档中的对话 ID，已被占用时会生成新的 ID')
    message_count: int = Field(description='导入的消息数')
