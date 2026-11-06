from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyCapabilityScope,
    AIBuddyChatGenerationType,
    AIBuddyChatThinkingType,
    AIBuddyKnowledgeFileType,
    AIBuddyMessageRole,
    AIBuddyModelCapability,
    AIBuddyModelKind,
    AIBuddyModelModality,
    AIBuddyOrigin,
    AIBuddyPermissionMode,
    AIBuddyProviderType,
    AIBuddyToolPolicy,
)

if TYPE_CHECKING:
    from ag_ui.core import RunAgentInput
    from pydantic_ai import ModelRequest, ModelResponse
    from pydantic_ai.capabilities import AbstractCapability
    from pydantic_ai.messages import BinaryContent, ModelMessage, UserContent
    from pydantic_ai.models import Model
    from pydantic_ai.native_tools import AbstractNativeTool
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.plugin.ai_buddy.agent.coding.sandbox import CodingSandbox
    from backend.plugin.ai_buddy.agent.work.capabilities.base import CapabilityBuilder
    from backend.plugin.ai_buddy.model.conversation import AIBuddyConversation
    from backend.plugin.ai_buddy.model.message import AIBuddyMessage
    from backend.plugin.ai_buddy.provider.base import ProviderAdapter
    from backend.plugin.ai_buddy.schema.chat import AIBuddyForwardedPropsParam


ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """归一后的通道入站消息"""

    external_id: str
    text: str
    raw: dict[str, Any]
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteFile:
    """已下载的远程文件"""

    data: bytes
    content_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class ProviderModelSnapshot:
    """供应商返回的模型标识"""

    id: str
    object: str | None = None
    created: int | None = None
    display_name: str | None = None
    kind: AIBuddyModelKind = AIBuddyModelKind.chat
    capabilities: tuple[AIBuddyModelCapability, ...] = ()
    input_modalities: tuple[AIBuddyModelModality, ...] = (AIBuddyModelModality.text,)
    context_window: int | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class SkillUpload:
    """解析后的技能目录"""

    name: str
    description: str
    version: str
    content: str
    body: str
    files: tuple[tuple[str, bytes], ...] = ()


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    """知识检索命中"""

    knowledge_id: int
    title: str
    source: str | None
    content: str
    score: float


@dataclass(frozen=True, slots=True)
class AIBuddyInvocationContext:
    """AI 调用策略上下文"""

    provider_id: int
    provider_type: AIBuddyProviderType
    provider_name: str
    model_pk: int
    model_id: str
    user_id: int
    is_superuser: bool = False
    mcp_ids: tuple[int, ...] = ()
    generation_type: AIBuddyChatGenerationType | None = None
    conversation_id: str | None = None
    agent_mode: AIBuddyAgentMode = AIBuddyAgentMode.work
    permission_mode: AIBuddyPermissionMode | None = None


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
    read_only: bool = False
    is_mcp: bool = False


@dataclass(slots=True)
class BoundAgentTool:
    """已绑定的 Agent 工具"""

    spec: AgentToolSpec
    handler: ToolHandler


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


@dataclass(slots=True)
class CodingHostSpec:
    """打开编码宿主所需的 Buddy 侧规格"""

    run_context: AgentRunContext
    buddy_tools: list[BoundAgentTool]
    provider_type: AIBuddyProviderType
    model_id: str
    api_key: str
    api_host: str
    close_resources: Callable[[], Awaitable[None]] | None = None
    input_modalities: list[str] | None = None
    context_window: int | None = None
    thinking: AIBuddyChatThinkingType | None = None
    message_history: list[ModelMessage] = field(default_factory=list)
    compaction_enabled: bool | None = None
    compaction_keep_messages: int | None = None
    compaction_max_messages: int | None = None
    workspace_id: str | None = None
    forwarded_props: AIBuddyForwardedPropsParam | None = None
    user_content: list[UserContent] = field(default_factory=list)


@dataclass(slots=True)
class ChatAgentDeps:
    """聊天代理依赖"""

    user_id: int
    conversation_id: str | None = None
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatConversationState:
    """聊天上下文状态"""

    conversation: AIBuddyConversation | None
    message_rows: list[AIBuddyMessage]
    model_messages: list[ModelRequest | ModelResponse]
    row_model_message_ranges: list[tuple[int, int]]


@dataclass(frozen=True, slots=True)
class ChatRunContext:
    """AG-UI 运行请求与已校验的业务扩展参数"""

    conversation_id: str
    forwarded_props: AIBuddyForwardedPropsParam
    run_input: RunAgentInput


@dataclass(frozen=True, slots=True)
class CapabilityContext:
    """能力构建上下文"""

    db: AsyncSession
    adapter: ProviderAdapter
    forwarded_props: AIBuddyForwardedPropsParam
    user_id: int | None
    is_superuser: bool
    supports_tools: bool
    supported_native_tools: frozenset[type[AbstractNativeTool]]
    supports_image_output: bool
    has_builtin_tools: bool
    model: Model | None = None
    conversation_id: str | None = None
    conversation_goal: str | None = None
    project_name: str | None = None
    assistant_name: str | None = None
    assistant_prompt: str | None = None
    context_window: int | None = None
    catalog_capabilities: frozenset[AIBuddyModelCapability] = frozenset()
    origin: AIBuddyOrigin = AIBuddyOrigin.web


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    """单个构建器的产出"""

    capability: AbstractCapability[Any] | None
    introduces_builtin_tool: bool = False
    introduces_function_tool_source: bool = False


@dataclass(frozen=True, slots=True)
class CapabilityRegistration:
    """声明一个能力构建器及其适用模式范围"""

    builder: CapabilityBuilder
    scope: AIBuddyCapabilityScope


@dataclass(frozen=True, slots=True)
class CapabilityAssembly:
    """一次能力装配的最终结果与能力组合标记"""

    capabilities: tuple[AbstractCapability[Any], ...]
    has_builtin_tools: bool
    has_function_tool_source: bool


@dataclass(frozen=True, slots=True)
class CompletionPersistenceContext:
    """普通聊天完成持久化上下文"""

    conversation_id: str
    user_id: int
    forwarded_props: AIBuddyForwardedPropsParam
    title: str
    assistant_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class RegenerationPersistenceContext:
    """重生成完成持久化上下文"""

    conversation_id: str
    user_id: int
    forwarded_props: AIBuddyForwardedPropsParam
    assistant_message_id: int | None = None
    insert_before_index: int | None = None
    replace_start_index: int | None = None
    replace_end_index: int | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeSegment:
    """知识解析片段"""

    text: str | None = None
    image: bytes | None = None
    media_type: str | None = None
    placeholder: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeUpload:
    """解析后的知识文件"""

    title: str
    content: str
    source: str
    file_type: AIBuddyKnowledgeFileType
    segments: tuple[KnowledgeSegment, ...] = ()
