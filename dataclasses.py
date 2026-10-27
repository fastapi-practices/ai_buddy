from dataclasses import dataclass, field
from typing import Any

from ag_ui.core import RunAgentInput
from pydantic_ai import ModelRequest, ModelResponse
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models import Model
from pydantic_ai.native_tools import AbstractNativeTool
from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.ai_buddy.enums import AIBuddyModelCapability, AIBuddyOrigin
from backend.plugin.ai_buddy.model.conversation import AIBuddyConversation
from backend.plugin.ai_buddy.model.message import AIBuddyMessage
from backend.plugin.ai_buddy.provider.base import ProviderAdapter
from backend.plugin.ai_buddy.schema.chat import AIBuddyForwardedPropsParam


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
