from datetime import datetime
from typing import Any

from pydantic import Field

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.schema.chat_message import AIBuddyChatAgUiMessagesSnapshotDetail


class AIBuddyMessageHistoryQueryParam(SchemaBase):
    """AI 消息历史查询参数"""

    before: str | None = Field(None, description='上一页游标')
    limit: int = Field(50, description='单页消息数量')


class AIBuddyMessageSearchQueryParam(SchemaBase):
    """AI 消息历史搜索参数"""

    q: str = Field(description='搜索关键词')
    cursor: str | None = Field(None, description='分页游标')
    limit: int = Field(50, description='单页结果数量')


class ForkAIBuddyConversationParam(SchemaBase):
    """按消息边界复刻对话"""

    message_id: int | None = Field(None, description='截断边界的持久消息 ID，省略则复制整段对话')
    include_message: bool = Field(True, description='是否包含边界消息')


class GetAIBuddyMessagePageDetail(SchemaBase):
    """按消息顺序返回的一页历史"""

    messages_snapshot: AIBuddyChatAgUiMessagesSnapshotDetail = Field(description='当前页 AG-UI 消息快照，按时间正序')
    has_more: bool = Field(description='是否有更早消息')
    next_cursor: str | None = Field(None, description='继续读取更早消息的游标')


class GetAIBuddyMessageSearchHitDetail(SchemaBase):
    """历史正文搜索命中"""

    message_id: int = Field(description='持久消息 ID')
    snapshot_id: str = Field(description='命中的渲染消息 ID')
    message_index: int = Field(description='消息顺序')
    role: str = Field(description='消息角色')
    text: str = Field(description='命中片段的完整可见文本')
    excerpt: str = Field(description='匹配位置附近的文本')


class GetAIBuddyMessageSearchDetail(SchemaBase):
    """全历史正文搜索结果"""

    items: list[GetAIBuddyMessageSearchHitDetail] = Field(description='匹配消息')
    has_more: bool = Field(description='是否还有未搜索历史')
    next_cursor: str | None = Field(None, description='继续搜索游标')


class GetAIBuddyMessageVersionDetail(SchemaBase):
    """保留在独立会话中的消息版本"""

    conversation_id: str = Field(description='版本所属对话 ID')
    title: str = Field(description='对话标题')
    created_time: datetime = Field(description='创建时间')
    message_id: int | None = Field(None, description='新对话中对应的持久消息 ID')
    source_conversation_id: str = Field(description='最初来源对话 ID')
    source_message_id: int = Field(description='最初来源消息 ID')


class GetAIBuddyPlanDetail(SchemaBase):
    """现有代理维护的任务计划"""

    items: list[dict[str, Any]] = Field(
        default_factory=list, description='有序任务，含 id、content、status 和 subtasks'
    )
