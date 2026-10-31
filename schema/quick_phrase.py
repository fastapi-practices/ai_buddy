from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class AIBuddyQuickPhraseQueryParam(SchemaBase):
    """AI 快捷短语查询参数"""

    content: str | None = Field(None, description='短语内容')


class AIBuddyQuickPhraseSchemaBase(SchemaBase):
    """AI 快捷短语基础模型"""

    title: str = Field(description='短语标题')
    content: str = Field(description='短语内容')
    sort: int = Field(default=0, description='排序')


class CreateAIBuddyQuickPhraseParam(AIBuddyQuickPhraseSchemaBase):
    """创建 AI 快捷短语参数"""


class UpdateAIBuddyQuickPhraseParam(AIBuddyQuickPhraseSchemaBase):
    """更新 AI 快捷短语参数"""


class GetAIBuddyQuickPhraseDetail(AIBuddyQuickPhraseSchemaBase):
    """AI 快捷短语详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='快捷短语 ID')
    user_id: int = Field(description='用户 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
