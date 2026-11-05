from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from backend.plugin.ai_buddy.dataclasses import AgentMessage, AgentRunContext, AgentToolCall, AgentUsage
from backend.plugin.ai_buddy.enums import AIBuddyMessageStatus

PersistMessage = Callable[[AgentMessage], Awaitable[None]]
EmitEvent = Callable[[str, dict[str, Any]], Awaitable[None]]
CancelledCheck = Callable[[], Awaitable[bool]]
WaitApproval = Callable[[str, AgentToolCall], Awaitable[bool]]


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
