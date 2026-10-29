from typing import Literal

from pydantic import Field, model_validator

from backend.common.schema import SchemaBase


class ControlAIBuddyDelegationParam(SchemaBase):
    """本轮后台子代理控制参数"""

    run_id: str = Field(min_length=1, max_length=128, description='运行 ID')
    action: Literal['steer', 'stop']
    text: str | None = Field(None, max_length=8000, description='引导内容，引导操作必填')

    @model_validator(mode='after')
    def validate_steering(self) -> 'ControlAIBuddyDelegationParam':
        """引导操作必须包含有效指令"""
        if self.action == 'steer' and not (self.text or '').strip():
            raise ValueError('引导内容不能为空')
        return self
