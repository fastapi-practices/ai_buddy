from pydantic import Field

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyModelKind, AIBuddyModelModality
from backend.plugin.ai_buddy.schema.model import AIBuddyThinkingPolicy


class GetAIBuddyModelArchitectureDetail(SchemaBase):
    """模型目录提供的架构建议"""

    source: str = Field(description='数据来源')
    last_updated: str | None = Field(None, description='数据更新时间')
    kind: AIBuddyModelKind | None = Field(None, description='可用的模型类型建议')
    input_modalities: list[AIBuddyModelModality] | None = Field(None, description='输入模态建议')
    tools: bool | None = Field(None, description='工具能力建议')
    thinking: bool | None = Field(None, description='思考能力建议')
    thinking_policy: AIBuddyThinkingPolicy | None = Field(None, description='已确认可选的思考档位')
    context_window: int | None = Field(None, description='上下文窗口建议')
    max_output_tokens: int | None = Field(None, description='最大输出建议')


class GetAIBuddyModelArchitectureSyncSkippedDetail(SchemaBase):
    """未应用架构同步的模型"""

    id: int = Field(description='模型记录 ID')
    model_id: str = Field(description='模型 ID')
    reason: str = Field(description='未同步原因')


class GetAIBuddyModelArchitectureSyncDetail(SchemaBase):
    """全量模型架构同步结果"""

    updated_count: int = Field(0, description='已更新的模型数量')
    skipped: list[GetAIBuddyModelArchitectureSyncSkippedDetail] = Field(
        default_factory=list, description='未同步的模型与原因'
    )
