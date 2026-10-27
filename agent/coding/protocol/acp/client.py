from __future__ import annotations

import asyncio

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, NoReturn
from uuid import uuid4

from backend.plugin.ai_buddy.agent.coding.protocol.acp.permissions import ACPPermissionAdapter
from backend.plugin.ai_buddy.agent.coding.types import AgentToolCall
from backend.plugin.ai_buddy.enums import AIBuddyPermissionMode

if TYPE_CHECKING:
    from backend.plugin.ai_buddy.agent.coding.protocol.acp.models import ACPRunnerConfig, SuspendedPermission

MessageHandler = Callable[[dict[str, Any], bool], Awaitable[None]]
ApprovalWaiter = Callable[[str, AgentToolCall], Awaitable[bool]]


class ACPHostedClient:
    """ACP client 回调：收 session/update，把权限接到 Buddy HITL"""

    def __init__(
        self,
        *,
        runner_name: str,
        runner_config: ACPRunnerConfig,
        cwd: str,
        permission_mode: AIBuddyPermissionMode,
        wait_approval: ApprovalWaiter | None = None,
    ) -> None:
        """
        初始化 ACP 消息、权限与提示状态

        :param runner_name: ACP 执行器名称
        :param runner_config: ACP 执行器配置
        :param cwd: 当前执行目录
        :param permission_mode: 权限处理模式
        :param wait_approval: 外部权限审批回调
        :return:
        """
        self.runner_name = runner_name
        self.tool_parse_mode = runner_config.tool_parse_mode
        self._permission_mode = permission_mode
        self._wait_approval = wait_approval
        self._permission_adapter = ACPPermissionAdapter(cwd=cwd)
        self._on_message: MessageHandler | None = None
        self._assistant_text = ''
        self._pending_permission: SuspendedPermission | None = None
        self._permission_future: asyncio.Future[Any] | None = None
        self._permission_requested = asyncio.Event()

    @property
    def pending_permission(self) -> SuspendedPermission | None:
        """返回当前挂起的权限请求"""
        return self._pending_permission

    def set_wait_approval(self, wait_approval: ApprovalWaiter | None) -> None:
        """
        更新当前客户端使用的权限审批回调

        :param wait_approval: 外部权限审批回调
        :return:
        """
        self._wait_approval = wait_approval

    def update_cwd(self, cwd: str) -> None:
        """
        同步当前执行目录及其权限边界

        :param cwd: 当前执行目录
        :return:
        """
        self._permission_adapter = ACPPermissionAdapter(cwd=cwd)

    def start_prompt(self, on_message: MessageHandler) -> None:
        """
        重置本轮输出并绑定消息回调

        :param on_message: ACP 消息回调
        :return:
        """
        self._on_message = on_message
        self._assistant_text = ''
        self._pending_permission = None
        self._permission_requested.clear()

    def resume_prompt(self, on_message: MessageHandler) -> None:
        """
        恢复挂起提示的消息回调

        :param on_message: ACP 消息回调
        :return:
        """
        self._on_message = on_message
        self._permission_requested.clear()

    async def wait_for_permission_request(self) -> None:
        """等待 ACP 权限请求到达"""
        await self._permission_requested.wait()

    def resolve_permission(self, option_id: str) -> None:
        """
        校验并提交用户选择的权限选项

        :param option_id: 用户选择的权限选项 ID
        :return:
        """
        if self._pending_permission is None or self._permission_future is None:
            raise ValueError('当前没有待处理的 ACP 权限请求')
        selected = self._permission_adapter.resolve_option_by_id(self._pending_permission.options, option_id)
        if selected is None:
            raise ValueError('respond 必须使用提供选项中已选权限项的准确 ID')
        if not self._permission_future.done():
            self._permission_future.set_result(self._permission_adapter.selected_response(selected))

    async def request_permission(
        self,
        options: list[Any],
        session_id: str,
        tool_call: Any,
        **_: Any,
    ) -> Any:
        """
        依据策略处理 ACP 工具权限请求

        :param options: ACP 提供的权限选项
        :param session_id: ACP 会话 ID
        :param tool_call: ACP 工具调用信息
        :param _: 额外关键字参数
        :return:
        """
        del session_id
        suspended = self._permission_adapter.build_suspended_permission(
            runner=self.runner_name,
            tool_call=tool_call,
            options=options,
        )
        await self._emit_message(
            {
                'type': 'permission_request',
                'title': suspended.summary or suspended.tool_name,
                'options': suspended.options,
                'tool_kind': suspended.tool_kind,
                'tool_name': suspended.tool_name,
            },
            is_last=True,
        )
        if self._permission_adapter.is_hard_blocked(tool_call):
            return self._permission_adapter.cancelled_response()
        if self._permission_mode != AIBuddyPermissionMode.ask:
            allowed = self._permission_adapter.preferred_allow_option(suspended.options)
            return self._permission_adapter.selected_response(allowed)
        if self._wait_approval is not None:
            approved = await self._wait_approval(
                f'acp:{self.runner_name}',
                AgentToolCall(
                    id=f'acp-{uuid4().hex}',
                    name=suspended.tool_name,
                    arguments={
                        'runner': self.runner_name,
                        'kind': suspended.tool_kind,
                        'command': suspended.command,
                        'paths': suspended.paths,
                        'tool_call': suspended.payload.get('toolCall'),
                    },
                ),
            )
            if approved:
                allowed = self._permission_adapter.preferred_allow_option(suspended.options)
                return self._permission_adapter.selected_response(allowed)
            return self._permission_adapter.cancelled_response()

        self._pending_permission = suspended
        self._permission_requested.set()
        self._permission_future = asyncio.get_running_loop().create_future()
        try:
            return await self._permission_future
        finally:
            self._pending_permission = None
            self._permission_future = None
            self._permission_requested.clear()

    async def session_update(self, session_id: str, update: Any, **_: Any) -> None:
        """
        将 ACP 会话更新转换为统一消息事件

        :param session_id: ACP 会话 ID
        :param update: ACP 会话更新内容
        :param _: 额外关键字参数
        :return:
        """
        from acp.schema import (
            AgentMessageChunk,
            AgentPlanUpdate,
            AgentThoughtChunk,
            AvailableCommandsUpdate,
            CurrentModeUpdate,
            ToolCallProgress,
            ToolCallStart,
            UserMessageChunk,
        )

        del session_id
        if isinstance(update, AgentMessageChunk):
            text = _extract_text_from_content(update.content)
            if text:
                self._assistant_text += text
                await self._emit_message({'type': 'text', 'text': text, 'is_chunk': True}, is_last=False)
            return
        if isinstance(update, AgentThoughtChunk):
            text = _extract_text_from_content(update.content)
            if text:
                await self._emit_message({'type': 'thinking', 'text': text}, is_last=False)
            return
        if isinstance(update, ToolCallStart | ToolCallProgress):
            call_id = str(getattr(update, 'tool_call_id', '') or '')
            if not call_id:
                return
            title = str(getattr(update, 'title', None) or 'unknown')
            await self._emit_message(
                {
                    'type': 'tool_start' if isinstance(update, ToolCallStart) else 'tool_update',
                    'name': title,
                    'call_id': call_id,
                    'title': title,
                    'kind': str(getattr(update, 'kind', None) or 'other'),
                    'detail': title,
                    'status': getattr(update, 'status', None),
                    'raw_input': getattr(update, 'raw_input', None),
                    'raw_output': getattr(update, 'raw_output', None),
                },
                is_last=True,
            )
            return
        if isinstance(
            update,
            CurrentModeUpdate | AgentPlanUpdate | AvailableCommandsUpdate | UserMessageChunk,
        ):
            return

    async def read_text_file(
        self,
        session_id: str,
        path: str,
        line: int | None = None,
        limit: int | None = None,
        **_: Any,
    ) -> Any:
        """
        拒绝 ACP 访问服务端文件系统

        :param session_id: ACP 会话 ID
        :param path: 请求读取的文件路径
        :param line: 文件起始行号
        :param limit: 最大读取行数
        :param _: 额外关键字参数
        :return:
        """
        self._unsupported_method('fs/read_text_file')

    async def write_text_file(self, session_id: str, path: str, content: str, **_: Any) -> Any:
        """
        拒绝 ACP 修改服务端文件系统

        :param session_id: ACP 会话 ID
        :param path: 请求写入的文件路径
        :param content: 待写入的文件内容
        :param _: 额外关键字参数
        :return:
        """
        self._unsupported_method('fs/write_text_file')

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        拒绝未支持的 ACP 扩展方法

        :param method: ACP 扩展方法名称
        :param params: ACP 扩展方法参数
        :return:
        """
        del params
        self._unsupported_method(method)

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        """
        拒绝未支持的 ACP 扩展通知

        :param method: ACP 扩展通知名称
        :param params: ACP 扩展通知参数
        :return:
        """
        del params
        self._unsupported_method(method)

    @staticmethod
    def _unsupported_method(method: str) -> NoReturn:
        """
        抛出 ACP 方法未支持错误

        :param method: ACP 方法名称
        :return:
        """
        from acp import RequestError

        raise RequestError(code=-32601, message=f'不支持的 ACP 扩展方法：{method}')

    async def finish_prompt(self) -> dict[str, Any] | None:
        """汇总本轮输出并发送结束消息"""
        if self._assistant_text:
            return {'type': 'text', 'text': self._assistant_text, 'is_chunk': False}
        return None

    async def _emit_message(self, payload: dict[str, Any], *, is_last: bool) -> None:
        """
        向本轮消息回调发送 ACP 事件

        :param payload: ACP 事件载荷
        :param is_last: 是否为本轮最后一条消息
        :return:
        """
        if self._on_message is None:
            return
        await self._on_message(payload, is_last)


def _extract_text_from_content(content: Any) -> str:
    """
    从 ACP 内容块中提取文本

    :param content: ACP 内容块或内容块列表
    :return:
    """
    if hasattr(content, 'text') and isinstance(getattr(content, 'text', None), str):
        return str(content.text)
    if isinstance(content, list):
        return ''.join(part for part in (_extract_text_from_content(item) for item in content) if part)
    if isinstance(content, dict) and content.get('type') == 'text':
        return str(content.get('text') or '')
    return ''
