from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from backend.plugin.ai_buddy.enums import AIBuddyChatAttachmentSourceType, AIBuddyFollowUpMode, AIBuddyFollowUpStatus
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam
from backend.plugin.ai_buddy.schema.chat_base import AIBuddyChatSchemaBase
from backend.plugin.ai_buddy.schema.chat_message import AIBuddyChatAgUiInputContentParam


class SubmitAIBuddyFollowUpParam(AIBuddyChatSchemaBase):
    """提交持久跟进"""

    client_request_id: str = Field(min_length=1, max_length=128, description='客户端幂等 ID')
    mode: AIBuddyFollowUpMode = Field(default=AIBuddyFollowUpMode.queue, description='请求处理方式')
    content: str = Field(default='', max_length=200000, description='跟进文本')
    attachments: list[AIBuddyChatAgUiInputContentParam] = Field(default_factory=list, description='AG-UI 附件内容')
    forwarded_props: AIBuddyChatForwardedPropsParam = Field(description='本轮运行参数')

    @model_validator(mode='after')
    def validate_input(self) -> 'SubmitAIBuddyFollowUpParam':
        """拒绝空输入和不能持久引用的临时附件"""
        if not self.content.strip() and not self.attachments:
            raise ValueError('跟进内容不能为空')
        for attachment in self.attachments:
            source = getattr(attachment, 'source', None)
            if (
                source is not None
                and source.type == AIBuddyChatAttachmentSourceType.url
                and source.value.startswith('blob:')
            ):
                raise ValueError('附件需要持久 URL 或内联数据')
        return self


class UpdateAIBuddyFollowUpParam(AIBuddyChatSchemaBase):
    """修改待执行跟进"""

    content: str | None = Field(None, max_length=200000, description='跟进文本')
    attachments: list[AIBuddyChatAgUiInputContentParam] | None = Field(None, description='AG-UI 附件内容')
    forwarded_props: AIBuddyChatForwardedPropsParam | None = Field(None, description='本轮运行参数')
    position: int | None = Field(None, ge=0, description='待执行项中的零起始位置')

    @model_validator(mode='after')
    def validate_patch(self) -> 'UpdateAIBuddyFollowUpParam':
        """显式空值不能覆盖必填内容"""
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError('修改字段不能为 null')
        return self


class GetAIBuddyFollowUpDetail(AIBuddyChatSchemaBase):
    """持久跟进详情"""

    model_config = ConfigDict(from_attributes=True, alias_generator=to_camel, populate_by_name=True)

    id: int = Field(description='跟进 ID')
    client_request_id: str = Field(description='客户端幂等 ID')
    mode: AIBuddyFollowUpMode = Field(description='请求处理方式')
    content: str = Field(description='跟进文本')
    attachments: list[dict[str, Any]] = Field(description='AG-UI 附件内容')
    forwarded_props: dict[str, Any] = Field(description='本轮运行参数')
    position: int = Field(description='排队顺序')
    status: AIBuddyFollowUpStatus = Field(description='跟进状态')
    disposition: Literal[AIBuddyFollowUpStatus.queued, AIBuddyFollowUpStatus.steered] = Field(
        description='实际处理方式'
    )
    reason: str | None = Field(description='降级或失败原因')
    run_id: str | None = Field(description='派发运行 ID')
    message_id: int | None = Field(description='回复消息 ID')
    created_time: datetime = Field(description='提交时间')


class GetAIBuddyFollowUpsDetail(AIBuddyChatSchemaBase):
    """持久跟进列表"""

    items: list[GetAIBuddyFollowUpDetail] = Field(description='跟进记录')
