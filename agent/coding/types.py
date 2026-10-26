from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_ai.messages import BinaryContent, ModelMessage

    from backend.plugin.ai_buddy.agent.coding.sandbox import CodingSandbox
    from backend.plugin.ai_buddy.enums import AIBuddyMessageRole, AIBuddyPermissionMode, AIBuddyToolPolicy


@dataclass(slots=True)
class AgentToolCall:
    """模型发出的工具调用"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class AgentMessage:
    """Agent 内部消息"""

    role: AIBuddyMessageRole
    content: str | None = None
    tool_calls: list[AgentToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    thinking: str | None = None
    model_messages: list[ModelMessage] | None = None


@dataclass(slots=True)
class AgentUsage:
    """一次模型请求用量"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    request_count: int = 0
    tool_call_count: int = 0

    def add(self, other: AgentUsage) -> None:
        """
        累加用量

        :param other: 另一份用量
        :return:
        """
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.request_count += other.request_count
        self.tool_call_count += other.tool_call_count


@dataclass(frozen=True, slots=True)
class AgentToolSpec:
    """暴露给模型的工具定义"""

    name: str
    description: str
    parameters: dict[str, Any]
    mutating: bool = False
    is_mcp: bool = False


@dataclass(slots=True)
class AgentRunContext:
    """单次 Agent 运行上下文"""

    user_id: int
    is_superuser: bool
    conversation_id: str
    run_id: str
    permission_mode: AIBuddyPermissionMode
    sandbox: CodingSandbox | None
    project_name: str | None = None
    goal: str | None = None
    mcp_ids: tuple[int, ...] = ()
    workspace_refs: tuple[dict[str, Any], ...] = ()
    acp_runner_enabled: bool = False
    acp_runner_name: str | None = None
    acp_bridge_id: str | None = None
    acp_cwd: str | None = None
    tool_policies: dict[str, AIBuddyToolPolicy] = field(default_factory=dict)
    mcp_approve_writes: bool = False
    workspace_id: str | None = None
    input_attachments: tuple[BinaryContent, ...] = ()
