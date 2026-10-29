from datetime import datetime

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyConversationSource,
    AIBuddyConversationSurface,
    AIBuddyConversationView,
    AIBuddyOrigin,
)
from backend.plugin.ai_buddy.schema.chat_message import AIBuddyChatAgUiMessagesSnapshotDetail


class AIBuddyConversationQueryParam(SchemaBase):
    """AI 对话查询参数"""

    project_id: int | None = Field(None, description='项目 ID')
    assistant_id: int | None = Field(None, description='助手 ID')
    q: str | None = Field(None, description='标题关键字')
    archived: bool = Field(False, description='是否归档')
    surface: AIBuddyConversationSurface = Field(
        AIBuddyConversationSurface.chat,
        description='会话入口',
    )
    view: AIBuddyConversationView | None = Field(
        None,
        description='聊天列表视图，chat 和 work 显示所有模式，coding 显示工作与编码会话',
    )
    agent_mode: AIBuddyAgentMode | None = Field(None, description='按最近一轮模式精确筛选')


class AIBuddyConversationEventsHeaderParam(SchemaBase):
    """AI 对话生成流订阅请求头"""

    last_event_id: str | None = Field(
        None,
        pattern=r'^\d+-\d+$',
        description='客户端已收到的最后一个事件 ID，断线重连时从其后续传，不传则重放本轮全部事件',
    )


class AIBuddyConversationDetailQueryParam(SchemaBase):
    """AI 对话详情查询参数"""

    message_limit: int | None = Field(None, ge=1, le=100, description='最近消息数量上限')


class AIBuddyConversationSchemaBase(SchemaBase):
    """AI 对话基础模型"""

    conversation_id: str = Field(description='对话 ID')
    title: str = Field(description='对话标题')
    provider_id: int = Field(description='供应商 ID')
    model_id: str = Field(description='模型 ID')
    agent_mode: AIBuddyAgentMode | None = Field(None, description='最近一轮使用的会话模式')
    user_id: int = Field(description='用户 ID')
    project_id: int | None = Field(None, description='项目 ID')
    assistant_id: int | None = Field(None, description='助手 ID')
    goal: str | None = Field(None, description='对话目标')
    last_message_preview: str | None = Field(None, description='最后一条消息预览')
    last_message_time: datetime | None = Field(None, description='最后一条消息时间')
    pinned_time: datetime | None = Field(None, description='置顶时间')
    archived_time: datetime | None = Field(None, description='归档时间')


class CreateAIBuddyConversationParam(AIBuddyConversationSchemaBase):
    """创建对话参数"""

    origin: AIBuddyOrigin = Field(default=AIBuddyOrigin.web, description='对话来源')
    surface: AIBuddyConversationSurface = Field(default=AIBuddyConversationSurface.chat, description='会话入口')
    channel_id: int | None = Field(None, description='通道 ID')
    source: AIBuddyConversationSource = Field(
        AIBuddyConversationSource.cloud, description='会话事实源，local 表示以本机为准'
    )


class UpdateAIBuddyConversationParam(AIBuddyConversationSchemaBase):
    """更新对话参数"""


class UpdateAIBuddyConversationTitleParam(SchemaBase):
    """更新对话标题参数"""

    title: str = Field(description='对话标题')
    expected_revision: int | None = Field(
        None, ge=1, description='客户端读到的修订号，与当前不一致时返回冲突，不传则不检查'
    )


class UpdateAIBuddyConversationPinnedParam(SchemaBase):
    """更新对话置顶状态参数"""

    is_pinned: bool = Field(description='是否置顶')
    expected_revision: int | None = Field(
        None, ge=1, description='客户端读到的修订号，与当前不一致时返回冲突，不传则不检查'
    )


class UpdateAIBuddyConversationArchiveParam(SchemaBase):
    """更新对话归档状态参数"""

    is_archived: bool = Field(description='是否归档')
    expected_revision: int | None = Field(
        None, ge=1, description='客户端读到的修订号，与当前不一致时返回冲突，不传则不检查'
    )


class UpdateAIBuddyConversationSourceParam(SchemaBase):
    """迁移会话事实源参数"""

    source: AIBuddyConversationSource = Field(description='目标事实源')
    expected_revision: int | None = Field(
        None, ge=1, description='客户端读到的修订号，与当前不一致时返回冲突，不传则不检查'
    )


class ResolveAIBuddyCodingApprovalParam(SchemaBase):
    """编码工具审批结果"""

    approved: bool = Field(description='是否批准本次工具调用')


class UpdateAIBuddyConversationWorkspaceParam(SchemaBase):
    """更新对话工作区参数"""

    project_id: int | None = Field(None, description='项目 ID')
    assistant_id: int | None = Field(None, description='助手 ID')
    goal: str | None = Field(None, description='对话目标')
    expected_revision: int | None = Field(
        None, ge=1, description='客户端读到的修订号，与当前不一致时返回冲突，不传则不检查'
    )


class GetAIBuddyConversationListDetail(SchemaBase):
    """对话列表项"""

    model_config = ConfigDict(from_attributes=True, alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description='记录 ID')
    conversation_id: str = Field(description='对话 ID')
    title: str = Field(description='对话标题')
    agent_mode: AIBuddyAgentMode | None = Field(None, description='最近一轮使用的会话模式')
    project_id: int | None = Field(None, description='项目 ID')
    assistant_id: int | None = Field(None, description='助手 ID')
    origin: AIBuddyOrigin = Field(default=AIBuddyOrigin.web, description='对话来源')
    surface: AIBuddyConversationSurface = Field(default=AIBuddyConversationSurface.chat, description='会话入口')
    is_pinned: bool = Field(description='是否置顶')
    is_archived: bool = Field(default=False, description='是否归档')
    is_generating: bool = Field(default=False, description='是否正在生成')
    source: AIBuddyConversationSource = Field(default=AIBuddyConversationSource.cloud, description='会话事实源')
    last_message_preview: str | None = Field(None, description='最后一条消息预览')
    last_message_time: datetime | None = Field(None, description='最后一条消息时间')
    revision: int = Field(1, description='可变字段修订号，修改标题、置顶、归档、工作区时作为 expected_revision 回传')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class GetAIBuddyConversationDetail(SchemaBase):
    """对话详情"""

    model_config = ConfigDict(from_attributes=True, alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description='记录 ID')
    conversation_id: str = Field(description='对话 ID')
    title: str = Field(description='对话标题')
    agent_mode: AIBuddyAgentMode | None = Field(None, description='最近一轮使用的会话模式')
    project_id: int | None = Field(None, description='项目 ID')
    assistant_id: int | None = Field(None, description='助手 ID')
    goal: str | None = Field(None, description='对话目标')
    origin: AIBuddyOrigin = Field(default=AIBuddyOrigin.web, description='对话来源')
    surface: AIBuddyConversationSurface = Field(default=AIBuddyConversationSurface.chat, description='会话入口')
    is_pinned: bool = Field(description='是否置顶')
    is_archived: bool = Field(default=False, description='是否归档')
    is_generating: bool = Field(default=False, description='是否正在生成')
    source: AIBuddyConversationSource = Field(default=AIBuddyConversationSource.cloud, description='会话事实源')
    provider_id: int = Field(description='供应商 ID')
    model_id: str = Field(description='模型 ID')
    revision: int = Field(1, description='可变字段修订号，修改标题、置顶、归档、工作区时作为 expected_revision 回传')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
    messages_snapshot: AIBuddyChatAgUiMessagesSnapshotDetail = Field(description='AG-UI 对话消息快照')
    history_has_more: bool = Field(False, description='是否还有更早历史消息')
    history_cursor: str | None = Field(None, description='继续读取历史消息的游标')
