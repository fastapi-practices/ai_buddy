from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, field_validator

from backend.common.schema import SchemaBase


class AIBuddySkillQueryParam(SchemaBase):
    """AI 技能查询参数"""

    name: str | None = Field(None, description='技能名称')


class AIBuddySkillSearchQueryParam(SchemaBase):
    """AI 技能搜索参数"""

    q: str = Field(description='搜索词')


class AIBuddySkillSchemaBase(SchemaBase):
    """AI 技能基础模型"""

    name: str = Field(description='技能名称')
    description: str | None = Field(None, description='技能描述')
    version: str = Field(default='0.1.0', description='技能版本')


class CreateAIBuddySkillParam(AIBuddySkillSchemaBase):
    """创建 AI 技能参数"""


class UpdateAIBuddySkillParam(AIBuddySkillSchemaBase):
    """更新 AI 技能参数"""


class GetAIBuddySkillSearchDetail(AIBuddySkillSchemaBase):
    """技能系统搜索命中"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='技能 ID')
    user_id: int = Field(description='用户 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class GetAIBuddySkillDetail(AIBuddySkillSchemaBase):
    """AI 技能详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='技能 ID')
    user_id: int = Field(description='用户 ID')
    content: str = Field(description='技能内容')
    object_key: str | None = Field(None, description='S3 对象键')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class AIBuddySkillFrontmatter(SchemaBase):
    """技能 YAML 元数据"""

    model_config = ConfigDict(extra='allow')

    name: str | None = Field(None, description='技能名称')
    description: str = Field(description='技能描述')
    metadata: dict[str, str] | None = Field(None, description='技能元数据')

    @field_validator('name', mode='before')
    @classmethod
    def stringify_name(cls, value: Any) -> str | None:
        """
        将技能名称规范化为可选字符串

        :param value: YAML 技能名称
        :return:
        """
        if value is None:
            return None
        return str(value).strip() or None

    @field_validator('metadata', mode='before')
    @classmethod
    def stringify_metadata(cls, value: Any) -> dict[str, str] | None:
        """
        将技能元数据规范化为字符串映射

        :param value: YAML 技能元数据
        :return:
        """
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError('must be a mapping')

        normalized: dict[str, str] = {}
        for key, item in value.items():
            name = str(key).strip()
            if not name:
                continue
            if isinstance(item, dict | list):
                raise TypeError('must be a mapping of strings')
            normalized[name] = '' if item is None else str(item).strip()
        return normalized or None

    @field_validator('description', mode='after')
    @classmethod
    def strip_description(cls, value: str) -> str:
        """
        去除描述首尾空白并校验长度

        :param value: 技能描述
        :return:
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError('must not be empty')
        if len(stripped) > 1024:
            raise ValueError('must be at most 1024 characters')
        return stripped
