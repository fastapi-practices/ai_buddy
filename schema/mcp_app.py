from typing import Any

from pydantic import Field

from backend.common.schema import SchemaBase


class AIBuddyMcpAppScope(SchemaBase):
    """MCP 交互资源访问范围"""

    mcp_id: int = Field(gt=0, description='当前会话启用的 MCP ID')
    tool_name: str = Field(min_length=1, max_length=256, description='声明交互资源的原始工具名称')
    resource_uri: str = Field(pattern=r'^ui://', max_length=2048, description='工具声明的 UI 资源 URI')


class CallAIBuddyMcpAppToolParam(AIBuddyMcpAppScope):
    """调用 MCP 交互应用工具参数"""

    name: str = Field(min_length=1, max_length=256, description='应用请求调用的工具名称')
    arguments: dict[str, Any] = Field(default_factory=dict, description='工具调用参数')
    approved: bool = Field(default=False, description='宿主用户已批准本次写操作')


class GetAIBuddyMcpAppDetail(SchemaBase):
    """MCP 交互应用详情"""

    html: str = Field(description='MCP 交互资源 HTML')
    metadata: dict[str, Any] = Field(default_factory=dict, description='资源 CSP 和界面元数据')
    server_name: str = Field(description='MCP 名称')


class GetAIBuddyMcpAppToolInfoDetail(SchemaBase):
    """MCP 交互应用工具信息"""

    name: str = Field(description='工具名称')
    title: str = Field(description='工具展示名称')
    read_only: bool = Field(description='服务端声明该工具只读')
