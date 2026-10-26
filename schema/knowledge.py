from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyKnowledgeFileType


class AIBuddyKnowledgeDocumentAllQueryParam(SchemaBase):
    """AI 知识文档全集查询参数"""

    include_content: bool = Field(True, description='是否返回知识正文')


class AIBuddyKnowledgeDocumentQueryParam(SchemaBase):
    """AI 知识文档查询参数"""

    title: str | None = Field(None, description='知识标题')
    include_content: bool = Field(True, description='是否返回知识正文')


class AIBuddyKnowledgeSchemaBase(SchemaBase):
    """AI 知识文档基础模型"""

    title: str = Field(description='知识标题')
    source: str | None = Field(None, description='知识来源')


class CreateAIBuddyKnowledgeParam(AIBuddyKnowledgeSchemaBase):
    """创建 AI 知识文档参数"""

    knowledge_base_id: int = Field(description='知识库 ID')
    file_type: AIBuddyKnowledgeFileType = Field(
        AIBuddyKnowledgeFileType.txt, description='文档类型：md、txt、pdf、docx、pptx、xlsx、image'
    )
    provider_id: int | None = Field(None, description='向量化供应商 ID，空则使用知识库配置')
    model_id: str | None = Field(None, description='向量化模型 ID，空则使用知识库配置')


class GetAIBuddyKnowledgeDetail(AIBuddyKnowledgeSchemaBase):
    """AI 知识文档详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='知识文档 ID')
    user_id: int = Field(description='用户 ID')
    knowledge_base_id: int = Field(description='知识库 ID')
    file_type: AIBuddyKnowledgeFileType = Field(description='文档类型：md、txt、pdf、docx、pptx、xlsx、image')
    content: str = Field(description='知识内容')
    object_key: str | None = Field(None, description='S3 对象键')
    provider_id: int | None = Field(None, description='向量化供应商 ID')
    model_id: str | None = Field(None, description='向量化模型 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
