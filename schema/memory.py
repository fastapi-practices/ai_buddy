from pydantic import Field

from backend.common.schema import SchemaBase


class GetAIBuddyMemoryListDetail(SchemaBase):
    """记忆列表项"""

    path: str = Field(description='记忆路径')
    truncated: bool = Field(default=False, description='内容是否被截断')
    preview: str = Field(description='内容预览')


class GetAIBuddyMemoryDetail(SchemaBase):
    """记忆详情"""

    path: str = Field(description='记忆路径')
    content: str = Field(description='记忆内容')
    version: str = Field(description='版本')
    truncated: bool = Field(description='内容是否被截断')
