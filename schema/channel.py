from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, field_serializer

from backend.common.enums import StatusType
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyChannelQrcodeStatus, AIBuddyChannelType
from backend.plugin.ai_buddy.utils.sensitive_data import mask_sensitive_data


class AIBuddyChannelHitlQueryParam(SchemaBase):
    """AI 通道人工审批查询参数"""

    conversation_id: str = Field(description='对话 ID')
    tool_name: str = Field(description='工具名')
    reason: str = Field('', description='原因')


class AIBuddyChannelSchemaBase(SchemaBase):
    """AI 通道基础模型"""

    name: str = Field(description='通道名称')
    type: AIBuddyChannelType = Field(description='通道类型')
    config: dict[str, Any] | None = Field(None, description='通道配置')
    status: StatusType = Field(default=StatusType.enable, description='状态')
    show_thinking: bool = Field(default=True, description='是否展示思考过程')
    show_tool_hints: bool = Field(default=True, description='是否展示工具调用提示')


class CreateAIBuddyChannelParam(AIBuddyChannelSchemaBase):
    """创建 AI 通道参数"""


class UpdateAIBuddyChannelParam(AIBuddyChannelSchemaBase):
    """更新 AI 通道参数"""


class GetAIBuddyChannelDetail(AIBuddyChannelSchemaBase):
    """AI 通道详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='通道 ID')
    user_id: int = Field(description='用户 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @field_serializer('config')
    @staticmethod
    def serialize_sensitive_data(value: dict[str, Any] | None) -> dict[str, Any] | None:
        """
        脱敏序列化通道敏感配置

        :param value: 待处理值
        :return:
        """
        return mask_sensitive_data(value)


class GetAIBuddyChannelBindOptionDetail(SchemaBase):
    """通道绑定方式"""

    type: AIBuddyChannelType = Field(description='通道类型')
    qrcode: bool = Field(description='是否支持扫码')
    config_keys: list[str] = Field(description='手动填写时的配置键')


class CreateAIBuddyChannelQrcodePollParam(SchemaBase):
    """轮询通道扫码参数"""

    session_id: str = Field(description='扫码会话 ID')


class GetAIBuddyChannelQrcodeDetail(SchemaBase):
    """通道扫码结果"""

    session_id: str = Field(description='扫码会话 ID')
    type: AIBuddyChannelType = Field(description='通道类型')
    status: AIBuddyChannelQrcodeStatus = Field(description='扫码状态')
    qrcode_url: str | None = Field(None, description='二维码内容或链接')
    expire_in: int | None = Field(None, description='剩余有效秒数')
    channel: GetAIBuddyChannelDetail | None = Field(None, description='扫码成功后创建的通道')
    error: str | None = Field(None, description='失败原因')
