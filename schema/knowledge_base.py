from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase


class AIBuddyKnowledgeBaseQueryParam(SchemaBase):
    """AI 知识库查询参数"""

    name: str | None = Field(None, description='知识库名称')


class AIBuddyKnowledgeBaseSchemaBase(SchemaBase):
    """AI 知识库基础模型"""

    name: str = Field(max_length=128, description='知识库名称')
    description: str | None = Field(None, max_length=512, description='知识库描述')
    provider_id: int | None = Field(None, description='向量化供应商 ID，本地 ONNX 模型不填')
    model_id: str | None = Field(None, description='向量化模型 ID，本地 ONNX 模型需显式指定')


class CreateAIBuddyKnowledgeBaseParam(AIBuddyKnowledgeBaseSchemaBase):
    """创建 AI 知识库参数"""


class UpdateAIBuddyKnowledgeBaseParam(AIBuddyKnowledgeBaseSchemaBase):
    """更新 AI 知识库参数"""


class GetAIBuddyKnowledgeBaseDetail(AIBuddyKnowledgeBaseSchemaBase):
    """AI 知识库详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='知识库 ID')
    user_id: int = Field(description='用户 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
