from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic_ai.messages import ModelMessage, UserContent

from backend.plugin.ai_buddy.agent.coding.tools import BoundAgentTool
from backend.plugin.ai_buddy.agent.coding.types import AgentMessage, AgentRunContext, AgentToolCall, AgentUsage
from backend.plugin.ai_buddy.enums import AIBuddyChatThinkingType, AIBuddyMessageStatus, AIBuddyProviderType
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam

PersistMessage = Callable[[AgentMessage], Awaitable[None]]
EmitEvent = Callable[[str, dict[str, Any]], Awaitable[None]]
CancelledCheck = Callable[[], Awaitable[bool]]
WaitApproval = Callable[[str, AgentToolCall], Awaitable[bool]]


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
    forwarded_props: AIBuddyChatForwardedPropsParam | None = None
    user_content: list[UserContent] = field(default_factory=list)


class CodingHostSession(Protocol):
    """编码宿主会话"""

    run_context: AgentRunContext

    def resolve_ui(self, request_id: str, *, approved: bool) -> bool:
        """
        兑现宿主 UI 确认

        :param request_id: 请求 ID
        :param approved: 是否批准
        :return:
        """
        ...

    async def wait_ui(self, request_id: str) -> bool:
        """
        等待审批结果

        :param request_id: 请求 ID
        :return:
        """
        ...

    async def run(
        self,
        *,
        prompt: str,
        emit: EmitEvent,
        persist_message: PersistMessage,
        is_cancelled: CancelledCheck,
        wait_approval: WaitApproval | None = None,
    ) -> tuple[AIBuddyMessageStatus, AgentUsage]:
        """
        执行本轮提示并映射为 Buddy 编码流

        :param prompt: 用户提示
        :param emit: 事件回调
        :param persist_message: 消息落库
        :param is_cancelled: 取消检查
        :param wait_approval: 审批等待
        :return:
        """
        ...

    async def aclose(self) -> None:
        """关闭宿主资源"""
        ...


class CodingProtocolAdapter(Protocol):
    """编码宿主协议适配器"""

    name: str

    async def open_session(self, *, spec: CodingHostSpec) -> CodingHostSession:
        """
        按 Buddy 规格打开宿主会话

        :param spec: 宿主规格
        :return:
        """
        ...
