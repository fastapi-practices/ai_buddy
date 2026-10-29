from datetime import datetime
from typing import Annotated, Any

from pydantic import ConfigDict, Field, field_validator

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.schema.knowledge_base import GetAIBuddyKnowledgeBaseDetail
from backend.plugin.ai_buddy.schema.mcp import GetAIBuddyMcpDetail
from backend.plugin.ai_buddy.schema.skill import GetAIBuddySkillSearchDetail


class AIBuddyExpertQueryParam(SchemaBase):
    """AI 专家模板查询参数"""

    name: str | None = Field(None, description='专家名称')


class AIBuddyExpertSchemaBase(SchemaBase):
    """AI 专家模板基础模型"""

    name: str = Field(max_length=64, description='专家名称')
    prompt: str = Field(description='角色提示词')
    description: str | None = Field(None, max_length=512, description='专家描述')
    starters: list[Annotated[str, Field(max_length=256)]] = Field(
        default_factory=list,
        max_length=8,
        description='开场白列表',
    )
    mcp_ids: list[int] = Field(default_factory=list, description='默认 MCP ID 列表')
    skill_ids: list[int] = Field(default_factory=list, description='默认技能 ID 列表')
    knowledge_ids: list[int] = Field(default_factory=list, description='默认知识库 ID 列表')
    sort: int = Field(default=0, description='排序')

    @field_validator('starters', 'mcp_ids', 'skill_ids', 'knowledge_ids', mode='before')
    @classmethod
    def default_list(cls, value: list[Any] | None) -> list[Any]:
        """
        空值按空列表处理

        :param value: 待处理值
        :return:
        """
        return value or []


class CreateAIBuddyExpertParam(AIBuddyExpertSchemaBase):
    """创建 AI 专家模板参数"""


class UpdateAIBuddyExpertParam(AIBuddyExpertSchemaBase):
    """更新 AI 专家模板参数"""


class GetAIBuddyExpertDetail(AIBuddyExpertSchemaBase):
    """AI 专家模板详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='专家 ID')
    user_id: int = Field(description='用户 ID')
    usage_count: int = Field(default=0, description='使用次数')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class GetAIBuddyExpertWithRelationDetail(GetAIBuddyExpertDetail):
    """AI 专家模板详情（含关联数据）"""

    mcp_ids: list[int] = Field(default_factory=list, exclude=True, description='默认 MCP ID 列表')
    skill_ids: list[int] = Field(default_factory=list, exclude=True, description='默认技能 ID 列表')
    knowledge_ids: list[int] = Field(default_factory=list, exclude=True, description='默认知识库 ID 列表')
    mcps: list[GetAIBuddyMcpDetail] = Field(default_factory=list, description='默认 MCP 列表')
    skills: list[GetAIBuddySkillSearchDetail] = Field(default_factory=list, description='默认技能列表')
    knowledge_bases: list[GetAIBuddyKnowledgeBaseDetail] = Field(default_factory=list, description='默认知识库列表')


class ApplyAIBuddyExpertParam(SchemaBase):
    """专家一键填入助手参数"""

    name: str | None = Field(None, max_length=64, description='助手名称，空则使用专家名称')
