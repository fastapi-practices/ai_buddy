from typing import Any

from pydantic import Field

from backend.common.schema import SchemaBase


class AIBuddyMcpAppScope(SchemaBase):
    """MCP 交互资源访问范围"""

    mcp_id: int = Field(description='当前会话启用的 MCP ID')
    tool_name: str = Field(description='声明交互资源的原始工具名称')
    resource_uri: str = Field(pattern=r'^ui://', description='工具声明的 UI 资源 URI')


class AIBuddyMcpAppToolParam(AIBuddyMcpAppScope):
    """MCP 交互应用工具请求参数"""

    name: str = Field(description='应用请求调用的工具名称')
    arguments: dict[str, Any] = Field(default_factory=dict, description='工具调用参数')


class ApproveAIBuddyMcpAppToolParam(AIBuddyMcpAppToolParam):
    """申请 MCP 交互应用写操作审批票据"""


class CallAIBuddyMcpAppToolParam(AIBuddyMcpAppToolParam):
    """调用 MCP 交互应用工具参数"""

    approval_token: str | None = Field(
        None,
        min_length=20,
        max_length=256,
        description='宿主用户确认后签发的一次性审批票据，只读工具不需要',
    )


class GetAIBuddyMcpAppApprovalDetail(SchemaBase):
    """MCP 应用写操作审批票据"""

    approval_token: str = Field(description='绑定当前用户、会话、工具与参数的一次性票据')
    expires_in: int = Field(description='票据剩余有效秒数')


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
