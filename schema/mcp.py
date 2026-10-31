from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field, HttpUrl, field_serializer

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyMcpType
from backend.plugin.ai_buddy.utils.sensitive_data import mask_sensitive_data


class AIBuddyMcpQueryParam(SchemaBase):
    """AI MCP 查询参数"""

    name: str | None = Field(None, description='MCP 名称')
    type: int | None = Field(None, description='MCP 类型')


class AIBuddyMcpSchemaBase(SchemaBase):
    """AI MCP 基础模型"""

    name: str = Field(description='MCP 名称')
    command: str | None = Field(None, description='MCP 命令')
    type: AIBuddyMcpType = Field(AIBuddyMcpType.stdio, description='MCP 类型')
    description: str | None = Field(None, description='MCP 描述')
    url: HttpUrl | None = Field(None, description='MCP 端点链接')
    headers: dict[str, Any] | None = Field(None, description='请求 MCP 端点时的请求头')
    args: list[str] | None = Field(None, description='MCP 命令参数')
    env: dict[str, Any] | None = Field(None, description='MCP 环境变量')
    timeout: float = Field(5, description='客户端初始化超时时间（秒）')
    read_timeout: float = Field(5 * 60, description='等待新消息的最长时间（秒）')
    tool_prefix: str | None = Field(None, description='MCP 工具名称前缀')
    include_instructions: bool = Field(False, description='是否注入 MCP 服务说明')

    @field_serializer('url')
    @staticmethod
    def serialize_url(url: HttpUrl | None) -> str | None:
        """
        序列化 MCP 端点链接

        :param url: 请求地址
        :return:
        """
        return str(url) if url else None


class CreateAIBuddyMcpParam(AIBuddyMcpSchemaBase):
    """创建 AI MCP 参数"""


class UpdateAIBuddyMcpParam(AIBuddyMcpSchemaBase):
    """更新 AI MCP 参数"""


class ImportAIBuddyMcpParam(SchemaBase):
    """导入 MCP JSON 参数"""

    config: str = Field(description='Claude Desktop / Cursor mcpServers JSON')


class ImportAIBuddyMcpResult(SchemaBase):
    """导入 MCP 结果"""

    created: int = Field(description='新建条数')
    skipped: list[str] = Field(default_factory=list, description='因重名跳过的名称')


class GetAIBuddyMcpDetail(AIBuddyMcpSchemaBase):
    """AI MCP 详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='MCP ID')
    user_id: int = Field(description='用户 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')

    @field_serializer('headers', 'env')
    @staticmethod
    def serialize_sensitive_data(value: dict[str, Any] | None) -> dict[str, Any] | None:
        """
        脱敏序列化 MCP 敏感配置

        :param value: 待处理值
        :return:
        """
        return mask_sensitive_data(value)
