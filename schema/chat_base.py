from datetime import datetime
from typing import Any

from ag_ui.core import RunAgentInput
from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyChatMessageType


class AIBuddyChatSchemaBase(SchemaBase):
    """
    AI 聊天接口模型基础配置

    chat 接口（请求/响应）统一使用小驼峰参数
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra='forbid')


class AIBuddyRunAgentInput(RunAgentInput):
    """AG-UI 运行请求，严格使用官方线协议字段"""

    model_config = ConfigDict(extra='forbid')


class AIBuddyChatMessageUsageDetail(AIBuddyChatSchemaBase):
    """AI 对话消息用量"""

    input_tokens: int = Field(0, description='输入 token 数')
    output_tokens: int = Field(0, description='输出 token 数')
    total_tokens: int = Field(0, description='总 token 数')
    cache_read_tokens: int = Field(0, description='缓存读取 token 数')
    cache_write_tokens: int = Field(0, description='缓存写入 token 数')
    input_audio_tokens: int = Field(0, description='音频输入 token 数')
    output_audio_tokens: int = Field(0, description='音频输出 token 数')
    cache_audio_read_tokens: int = Field(0, description='缓存音频读取 token 数')
    details: dict[str, int] = Field(default_factory=dict, description='供应商用量明细')
    cost: float | None = Field(None, description='本轮费用（美元）')


class AIBuddyChatMessageMetaSchemaBase(AIBuddyChatSchemaBase):
    """AI 对话消息扩展元信息"""

    conversation_id: str | None = Field(None, description='对话 ID')
    persisted_message_id: int | None = Field(None, description='持久化消息 ID')
    provider_id: int | None = Field(None, description='供应商 ID')
    model_id: str | None = Field(None, description='模型 ID')
    message_type: AIBuddyChatMessageType | None = Field(
        None,
        description='消息类型',
    )
    message_index: int | None = Field(None, description='消息索引')
    created_time: datetime | None = Field(None, description='创建时间')
    turn_context: dict[str, Any] | None = Field(None, description='本轮实际组合')
