from pydantic import ConfigDict, Field, model_validator

from backend.common.schema import SchemaBase


class AIBuddyMessageQuote(SchemaBase):
    """用户消息的引用定位锚点"""

    model_config = ConfigDict(populate_by_name=True)
    message_id: str = Field(alias='messageId', description='来源渲染消息 ID')
    text: str = Field(description='选中的原文')
    conversation_id: str | None = Field(None, alias='conversationId', description='来源对话 ID')
    occurrence: int | None = Field(None, description='同段原文在来源消息中的出现序号')
    start: int | None = Field(None, description='选区在来源消息中的起始偏移')
    end: int | None = Field(None, description='选区在来源消息中的结束偏移')
    prefix: str | None = Field(None, description='选区之前的定位文本')
    suffix: str | None = Field(None, description='选区之后的定位文本')

    @model_validator(mode='after')
    def validate_range(self) -> 'AIBuddyMessageQuote':
        """同时提供起止偏移时校验选区顺序"""
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError('引用结束偏移不能小于起始偏移')
        return self
