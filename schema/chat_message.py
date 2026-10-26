from typing import Annotated, Any

from ag_ui.core import (
    ActivityMessage,
    AssistantMessage,
    AudioInputContent,
    DeveloperMessage,
    DocumentInputContent,
    ImageInputContent,
    MessagesSnapshotEvent,
    ReasoningMessage,
    SystemMessage,
    TextInputContent,
    ToolMessage,
    UserMessage,
    VideoInputContent,
)
from pydantic import Field

from backend.plugin.ai_buddy.schema.chat_base import (
    AIBuddyChatMessageMetaSchemaBase,
    AIBuddyChatMessageUsageDetail,
    AIBuddyChatSchemaBase,
)
from backend.plugin.ai_buddy.schema.citation import AIBuddyCitationDetail

type AIBuddyChatAgUiInputContentParam = Annotated[
    TextInputContent | ImageInputContent | AudioInputContent | VideoInputContent | DocumentInputContent,
    Field(discriminator='type'),
]


class AIBuddyChatAgUiUserMessageInput(UserMessage, AIBuddyChatSchemaBase):
    """AI 对话用户输入消息参数"""

    content: str | list[AIBuddyChatAgUiInputContentParam] = Field(description='用户输入内容')


type AIBuddyChatAgUiInputMessageParam = AIBuddyChatAgUiUserMessageInput


class AIBuddyChatAgUiUserMessageDetail(UserMessage, AIBuddyChatMessageMetaSchemaBase):
    """AI 对话用户消息详情"""

    content: str | list[AIBuddyChatAgUiInputContentParam] = Field(description='用户消息内容')


class AIBuddyChatAgUiDeveloperMessageDetail(DeveloperMessage, AIBuddyChatMessageMetaSchemaBase):
    """AI 对话开发者消息详情"""


class AIBuddyChatAgUiSystemMessageDetail(SystemMessage, AIBuddyChatMessageMetaSchemaBase):
    """AI 对话系统消息详情"""


class AIBuddyChatAgUiAssistantMessageDetail(AssistantMessage, AIBuddyChatMessageMetaSchemaBase):
    """AI 对话助手消息详情"""

    sources: list[AIBuddyCitationDetail] = Field(default_factory=list, description='供应商明确返回的网页引用')
    error: str | None = Field(None, description='运行错误信息')
    error_detail: dict[str, Any] | None = Field(None, description='运行错误详情')
    usage: AIBuddyChatMessageUsageDetail | None = Field(None, description='本轮模型用量与费用')


class AIBuddyChatAgUiReasoningMessageDetail(ReasoningMessage, AIBuddyChatMessageMetaSchemaBase):
    """AI 对话推理消息详情"""


class AIBuddyChatAgUiToolMessageDetail(ToolMessage, AIBuddyChatMessageMetaSchemaBase):
    """AI 对话工具消息详情"""


class AIBuddyChatAgUiActivityMessageDetail(ActivityMessage, AIBuddyChatMessageMetaSchemaBase):
    """AI 对话活动消息详情"""

    content: dict[str, Any] = Field(description='活动消息内容')


type AIBuddyChatAgUiSnapshotMessageDetail = Annotated[
    AIBuddyChatAgUiUserMessageDetail
    | AIBuddyChatAgUiDeveloperMessageDetail
    | AIBuddyChatAgUiAssistantMessageDetail
    | AIBuddyChatAgUiSystemMessageDetail
    | AIBuddyChatAgUiToolMessageDetail
    | AIBuddyChatAgUiReasoningMessageDetail
    | AIBuddyChatAgUiActivityMessageDetail,
    Field(discriminator='role'),
]


class AIBuddyChatAgUiMessagesSnapshotDetail(MessagesSnapshotEvent):
    """AI 对话消息快照详情"""

    messages: list[AIBuddyChatAgUiSnapshotMessageDetail] = Field(description='消息快照列表')
