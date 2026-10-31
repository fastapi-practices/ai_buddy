from pydantic import Field, SecretStr, model_validator

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyInputQuestionKind


class AIBuddyInputOption(SchemaBase):
    """结构化问题选项"""

    id: str = Field(description='选项 ID')
    label: str = Field(description='选项显示文本')


class AIBuddyInputQuestion(SchemaBase):
    """单题结构"""

    id: str = Field(description='题目 ID')
    prompt: str = Field(description='题目')
    kind: AIBuddyInputQuestionKind = Field(AIBuddyInputQuestionKind.text, description='作答方式')
    options: list[AIBuddyInputOption] = Field(default_factory=list, description='可选答案')
    required: bool = Field(True, description='是否必答')

    @model_validator(mode='after')
    def validate_options(self) -> 'AIBuddyInputQuestion':
        """校验选择题选项存在且 ID 唯一"""
        if self.kind != AIBuddyInputQuestionKind.text and not self.options:
            raise ValueError('选择题必须有选项')
        if len({item.id for item in self.options}) != len(self.options):
            raise ValueError('选项 ID 不能重复')
        return self


class ResolveAIBuddyInputRequestParam(SchemaBase):
    """结构化输入回复，密钥值不进入普通消息"""

    answers: dict[str, str | list[str]] | None = Field(None, description='按题目 ID 映射的答案')
    secret: SecretStr | None = Field(None, description='仅用于当前秘密请求的值')
    cancelled: bool = Field(False, description='用户取消当前输入请求')


class GetAIBuddyInputRequestsDetail(SchemaBase):
    """当前运行未决输入请求"""

    items: list[dict] = Field(default_factory=list, description='未决请求的公开内容')
