from __future__ import annotations

import asyncio
import contextlib

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.plugin.ai_buddy.agent.coding.protocol.acp.bridge import get_bridge, open_bridge_transport
from backend.plugin.ai_buddy.agent.coding.protocol.acp.client import ACPHostedClient
from backend.plugin.ai_buddy.agent.coding.protocol.acp.models import ACPConfig, ACPError
from backend.plugin.ai_buddy.agent.coding.protocol.acp.tool_adapter import build_acp_prompt
from backend.plugin.ai_buddy.agent.coding.types import AgentToolCall

if TYPE_CHECKING:
    from acp.schema import PromptCapabilities
    from pydantic_ai.messages import BinaryContent

    from backend.plugin.ai_buddy.enums import AIBuddyPermissionMode

MessageHandler = Callable[[dict[str, Any], bool], Awaitable[None]]
ApprovalWaiter = Callable[[str, AgentToolCall], Awaitable[bool]]


@dataclass
class _Conversation:
    thread_id: str
    runner: str
    acp_session_id: str
    cwd: str
    conn: Any
    client: ACPHostedClient
    transport: Any
    turn_lock: asyncio.Lock
    prompt_capabilities: PromptCapabilities | None = None
    prompt_task: asyncio.Task[Any] | None = None
    closed: bool = False


class ACPService:
    """通过桌面连接使用用户本机的 ACP agent"""

    def __init__(
        self,
        *,
        config: ACPConfig,
        bridge_id: str,
        user_id: int,
        cwd: str,
        permission_mode: AIBuddyPermissionMode,
        wait_approval: ApprovalWaiter | None = None,
        input_attachments: tuple[BinaryContent, ...] = (),
        imported_attachment_hashes: frozenset[str] = frozenset(),
    ) -> None:
        """
        初始化桌面 ACP 服务及会话注册表

        :param config: ACP 执行器配置
        :param bridge_id: 桌面桥接连接 ID
        :param user_id: 当前用户 ID
        :param cwd: 默认执行目录
        :param permission_mode: 权限处理模式
        :param wait_approval: 外部权限审批回调
        :param input_attachments: 本轮用户主动提交的附件
        :param imported_attachment_hashes: 桌面端已导入工作区的附件摘要
        :return:
        """
        self.config = config
        self._bridge_id = bridge_id
        self._user_id = user_id
        self.cwd = cwd
        self._permission_mode = permission_mode
        self._wait_approval = wait_approval
        self._lock = asyncio.Lock()
        self._sessions: dict[tuple[str, str], _Conversation] = {}
        self._on_event: MessageHandler | None = None
        self._input_attachments = input_attachments
        self._imported_attachment_hashes = imported_attachment_hashes

    def set_event_handler(self, handler: MessageHandler) -> None:
        """
        将外部 Agent 的执行进度转发给本轮界面

        :param handler: 本轮消息回调
        :return:
        """
        self._on_event = handler

    async def _relay_message(self, handler: MessageHandler, payload: dict[str, Any], is_last: object) -> None:
        """
        同时转发 ACP 消息到界面和本轮回调

        :param handler: 本轮消息回调
        :param payload: ACP 消息载荷
        :param is_last: 是否为本轮最后一条消息
        :return:
        """
        if self._on_event is not None:
            await self._on_event(payload, bool(is_last))
        await handler(payload, bool(is_last))

    def set_wait_approval(self, wait_approval: ApprovalWaiter | None) -> None:
        """
        本轮 HITL 回调，挂到已打开的 ACP 会话

        :param wait_approval: 外部权限审批回调
        :return:
        """
        self._wait_approval = wait_approval
        for conversation in self._sessions.values():
            conversation.client.set_wait_approval(wait_approval)

    async def run_turn(
        self,
        *,
        thread_id: str,
        runner: str,
        prompt_blocks: list[dict[str, Any]],
        cwd: str,
        on_message: MessageHandler,
        restart: bool = False,
        require_existing: bool = False,
    ) -> dict[str, Any]:
        """
        在绑定的 ACP 会话中执行一轮提示

        :param thread_id: 对话 ID
        :param runner: runner 名称
        :param prompt_blocks: 提示内容块
        :param cwd: 本轮工作目录
        :param on_message: 消息回调
        :param restart: 是否重建会话
        :param require_existing: 是否仅使用已有会话
        :return:
        """
        if restart:
            await self.close_thread_session(thread_id=thread_id, runner=runner)
        conversation = await self._get_or_create_session(
            thread_id=thread_id,
            runner=runner,
            require_existing=require_existing,
        )
        async with conversation.turn_lock:
            if conversation.client.pending_permission is not None:
                raise ACPError(f'会话 {conversation.acp_session_id} 正在等待权限审批')
            if conversation.prompt_task is not None and not conversation.prompt_task.done():
                raise ACPError(f'会话 {conversation.acp_session_id} 正在处理当前轮次')
            conversation.cwd = cwd or conversation.cwd
            conversation.client.update_cwd(conversation.cwd)

            async def relay(payload: dict[str, Any], is_last: object) -> None:
                """
                将本轮 ACP 消息转发给绑定的回调

                :param payload: ACP 消息载荷
                :param is_last: 是否为本轮最后一条消息
                :return:
                """
                await self._relay_message(on_message, payload, is_last)

            conversation.client.start_prompt(relay)
            prompt = build_acp_prompt(
                blocks=prompt_blocks,
                attachments=self._input_attachments,
                capabilities=conversation.prompt_capabilities,
                imported_hashes=self._imported_attachment_hashes,
            )
            conversation.prompt_task = asyncio.create_task(
                conversation.conn.prompt(
                    session_id=conversation.acp_session_id,
                    prompt=prompt,
                ),
            )
            return await self._wait_for_prompt_outcome(conversation=conversation)

    async def resume_permission(
        self,
        *,
        acp_session_id: str,
        option_id: str,
        on_message: MessageHandler,
    ) -> dict[str, Any]:
        """
        提交权限选项并恢复挂起的 ACP 提示

        :param acp_session_id: ACP 会话 ID
        :param option_id: 权限选项 ID
        :param on_message: 消息回调
        :return:
        """
        async with self._lock:
            conversation = next(
                (session for session in self._sessions.values() if session.acp_session_id == acp_session_id),
                None,
            )
        if conversation is None:
            raise ACPError(f'未找到会话：{acp_session_id}')
        if conversation.client.pending_permission is None:
            raise ACPError(f'会话 {acp_session_id} 没有待处理的权限请求')
        if conversation.prompt_task is None or conversation.prompt_task.done():
            raise ACPError(f'会话 {acp_session_id} 当前不在等待权限恢复')
        async with conversation.turn_lock:

            async def relay(payload: dict[str, Any], is_last: object) -> None:
                """
                将本轮 ACP 消息转发给绑定的回调

                :param payload: ACP 消息载荷
                :param is_last: 是否为本轮最后一条消息
                :return:
                """
                await self._relay_message(on_message, payload, is_last)

            conversation.client.resume_prompt(relay)
            conversation.client.resolve_permission(option_id)
            return await self._wait_for_prompt_outcome(conversation=conversation)

    async def close_thread_session(self, *, thread_id: str, runner: str) -> None:
        """
        移除并关闭指定对话的 ACP 会话

        :param thread_id: 对话 ID
        :param runner: ACP 执行器名称
        :return:
        """
        async with self._lock:
            conversation = self._sessions.pop((thread_id, runner), None)
        if conversation is not None:
            await self._close_conversation(conversation)

    async def check_connection(self, *, thread_id: str, runner: str) -> None:
        """
        只执行 ACP 握手和会话初始化，不发送提示或生成请求

        :param thread_id: 对话 ID
        :param runner: ACP 执行器名称
        :return:
        """
        await self._get_or_create_session(thread_id=thread_id, runner=runner, require_existing=False)
        await get_bridge(bridge_id=self._bridge_id, user_id=self._user_id, runner=runner)

    async def close_all_sessions(self) -> None:
        """回收所有 ACP 会话并传播关闭失败"""
        async with self._lock:
            conversations = list(self._sessions.values())
            self._sessions.clear()
        results = await asyncio.gather(
            *(self._close_conversation(item) for item in conversations), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def _get_session(self, thread_id: str, runner: str) -> _Conversation | None:
        """
        在锁保护下读取 ACP 会话

        :param thread_id: 对话 ID
        :param runner: ACP 执行器名称
        :return:
        """
        async with self._lock:
            return self._sessions.get((thread_id, runner))

    async def session_is_open(self, *, thread_id: str, runner: str) -> bool:
        """
        判断当前线程是否有仍处于打开状态的 ACP 会话

        :param thread_id: 对话 ID
        :param runner: ACP 执行器名称
        :return:
        """
        conversation = await self._get_session(thread_id, runner)
        return conversation is not None and not conversation.closed

    async def get_session_id(self, *, thread_id: str, runner: str) -> str | None:
        """
        获取当前线程绑定的 ACP 会话 ID

        :param thread_id: 对话 ID
        :param runner: ACP 执行器名称
        :return:
        """
        conversation = await self._get_session(thread_id, runner)
        return conversation.acp_session_id if conversation is not None and not conversation.closed else None

    async def get_pending_permission(self, *, thread_id: str, runner: str) -> Any | None:
        """
        读取 ACP 会话挂起的审批请求

        :param thread_id: 对话 ID
        :param runner: ACP 执行器名称
        :return:
        """
        conversation = await self._get_session(thread_id, runner)
        if conversation is None:
            return None
        return conversation.client.pending_permission

    async def cancel_turn(self, *, thread_id: str, runner: str) -> bool:
        """
        取消当前 ACP 提示并确认任务是否停止

        :param thread_id: 对话 ID
        :param runner: ACP 执行器名称
        :return:
        """
        conversation = await self._get_session(thread_id, runner)
        if conversation is None:
            return False
        prompt_task = conversation.prompt_task
        if prompt_task is None or prompt_task.done():
            return False
        try:
            await asyncio.wait_for(conversation.conn.cancel(session_id=conversation.acp_session_id), timeout=2)
        except (TimeoutError, OSError, RuntimeError):
            return False
        try:
            await asyncio.wait_for(asyncio.shield(prompt_task), timeout=0.5)
        except (TimeoutError, OSError, RuntimeError):
            return prompt_task.done()
        return prompt_task.done()

    async def _get_or_create_session(
        self,
        *,
        thread_id: str,
        runner: str,
        require_existing: bool,
    ) -> _Conversation:
        """
        复用 ACP 会话或完成桌面握手与初始化

        :param thread_id: 对话 ID
        :param runner: ACP 执行器名称
        :param require_existing: 是否仅使用已有会话
        :return:
        """
        runner_config = self.config.runners.get(runner)
        if runner_config is None:
            raise ACPError(f'未知的 ACP 执行器：{runner}', runner=runner)
        if not runner_config.enabled:
            raise ACPError(f"ACP 执行器 '{runner}' 已禁用", runner=runner)
        if not runner_config.command.strip():
            raise ACPError(f"ACP 执行器 '{runner}' 未配置启动命令", runner=runner)
        async with self._lock:
            existing = self._sessions.get((thread_id, runner))
            if existing is not None and not existing.closed:
                return existing
            if require_existing:
                raise ACPError(f"当前线程没有绑定执行器 '{runner}' 的 ACP 会话")
            from acp import PROTOCOL_VERSION, connect_to_agent
            from acp.schema import ClientCapabilities, Implementation

            client = ACPHostedClient(
                runner_name=runner,
                runner_config=runner_config,
                cwd=self.cwd,
                permission_mode=self._permission_mode,
                wait_approval=self._wait_approval,
            )
            transport = await open_bridge_transport(
                bridge_id=self._bridge_id, user_id=self._user_id, runner=runner, conversation_id=thread_id
            )
            conn = None
            try:
                conn = connect_to_agent(client, transport, use_unstable_protocol=True)
                async with asyncio.timeout(30):
                    initialized = await conn.initialize(
                        protocol_version=PROTOCOL_VERSION,
                        client_capabilities=ClientCapabilities(),
                        client_info=Implementation(name='ai-buddy-acp', version='0.1.0'),
                    )
                    if initialized.protocol_version != PROTOCOL_VERSION:
                        raise ACPError(
                            f'ACP 协议版本不兼容：Agent 返回 {initialized.protocol_version}，'
                            f'客户端支持 {PROTOCOL_VERSION}'
                        )
                    new_session = await conn.new_session(cwd=self.cwd, mcp_servers=[])
            except BaseException:
                with contextlib.suppress(Exception):
                    if conn is not None:
                        await asyncio.wait_for(conn.close(), timeout=2)
                with contextlib.suppress(Exception):
                    await transport.close()
                raise
            conversation = _Conversation(
                thread_id=thread_id,
                runner=runner,
                acp_session_id=new_session.session_id,
                cwd=self.cwd,
                conn=conn,
                client=client,
                transport=transport,
                turn_lock=asyncio.Lock(),
                prompt_capabilities=(
                    initialized.agent_capabilities.prompt_capabilities
                    if initialized.agent_capabilities is not None
                    else None
                ),
            )
            self._sessions[thread_id, runner] = conversation
        return conversation

    @staticmethod
    async def _wait_for_prompt_outcome(*, conversation: _Conversation) -> dict[str, Any]:
        """
        等待模型输出完成或进入权限审批状态

        :param conversation: ACP 对话状态
        :return:
        """
        prompt_task = conversation.prompt_task
        if prompt_task is None:
            raise ACPError('ACP 提示任务不存在')
        permission_task = asyncio.create_task(conversation.client.wait_for_permission_request())
        try:
            done, _ = await asyncio.wait({prompt_task, permission_task}, return_when=asyncio.FIRST_COMPLETED)
            if permission_task in done and conversation.client.pending_permission is not None:
                finished_event = await conversation.client.finish_prompt()
                return {
                    'status': 'permission_required',
                    'suspended_permission': conversation.client.pending_permission,
                    'event': finished_event,
                }
            permission_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await permission_task
            try:
                response = await prompt_task
            except Exception as exc:
                conversation.prompt_task = None
                await conversation.client.finish_prompt()
                raise ACPError(f'ACP 提示执行失败：{exc}') from exc
            conversation.prompt_task = None
            finished_event = await conversation.client.finish_prompt()
            pending = conversation.client.pending_permission
            if pending is not None:
                return {
                    'status': 'permission_required',
                    'suspended_permission': pending,
                    'event': finished_event,
                }
            usage = getattr(response, 'usage', None)
            stop_reason = getattr(response, 'stop_reason', None)
            return {
                'status': 'completed' if stop_reason == 'end_turn' else 'interrupted',
                'event': finished_event,
                'stop_reason': stop_reason,
                'usage': usage.model_dump(mode='json') if usage is not None else None,
            }
        finally:
            if not permission_task.done():
                permission_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await permission_task

    @staticmethod
    async def _close_conversation(conversation: _Conversation) -> None:
        """
        取消提示任务并关闭 ACP 连接与传输资源

        :param conversation: ACP 对话状态
        :return:
        """
        conversation.closed = True
        try:
            if conversation.prompt_task is not None and not conversation.prompt_task.done():
                conversation.prompt_task.cancel()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await conversation.prompt_task
            with contextlib.suppress(Exception):
                await asyncio.wait_for(
                    conversation.conn.close_session(session_id=conversation.acp_session_id),
                    timeout=5.0,
                )
        finally:
            try:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(conversation.conn.close(), timeout=2)
            finally:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(conversation.transport.close(), timeout=2)
