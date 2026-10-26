import asyncio
import json

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from functools import partial
from typing import Any

import anyio

from ag_ui.core import BaseEvent, RunAgentInput, RunErrorEvent, RunFinishedEvent, StateSnapshotEvent
from pydantic_ai import (
    AgentRunResult,
    BinaryImage,
    FilePart,
    RunCancelled,
    ToolApproved,
    capture_run_messages,
)
from starlette.responses import StreamingResponse

from backend.common.exception import errors
from backend.common.log import log
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.work.ag_ui import BuddyAGUIAdapter
from backend.plugin.ai_buddy.agent.work.inputs import (
    build_frontend_tool_results,
    mark_frontend_tool_requests,
)
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store
from backend.plugin.ai_buddy.agent.work.runs import (
    ActiveChatRun,
    build_run_stream_response,
    discard_run,
    finish_run,
    monitor_shared_run,
    register_run,
)
from backend.plugin.ai_buddy.agent.work.types import ChatAgent, ChatModelMessage
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.dataclasses import ChatAgentDeps
from backend.plugin.ai_buddy.service.approval_audit_service import ai_buddy_approval_audit_service
from backend.plugin.ai_buddy.utils.ag_ui import encode_ag_ui_event
from backend.plugin.ai_buddy.utils.run_error import build_run_error_payload


class StreamLifecycle:
    """流式回调生命周期"""

    def __init__(
        self,
        *,
        on_complete: Callable[[AgentRunResult[Any]], Awaitable[None]],
        on_run_error: Callable[[str, list[ChatModelMessage], dict[str, Any] | None], Awaitable[None]],
        on_interrupted: Callable[[list[ChatModelMessage]], Awaitable[None]],
    ) -> None:
        """保存生成完成、异常和中断回调

        :param on_complete: 完成回调
        :param on_run_error: 运行错误回调
        :param on_interrupted: 中断回调
        :return:
        """
        self.on_complete = on_complete
        self.on_run_error = on_run_error
        self.on_interrupted = on_interrupted
        self.run_finished = False
        self.error_message: str | None = None
        self.error_detail: dict[str, Any] | None = None

    async def complete(self, result: AgentRunResult[Any]) -> None:
        """
        幂等执行完成回调

        :param result: 代理运行结果
        :return:
        """
        if self.run_finished or self.error_message is not None:
            return
        try:
            await self.on_complete(result)
        except Exception as exc:
            # 完成回调失败时走错误终态，避免再被当成客户端中断导致 pending 锁死或状态打架
            if self.error_message is None:
                self.record_error(exc)
            raise
        else:
            self.run_finished = True

    def record_error(self, error: BaseException | str, *, extra: dict[str, Any] | None = None) -> None:
        """
        记录运行错误，异常细节可覆盖纯文本

        :param error: 异常或错误文本
        :param extra: 协议事件附加字段
        :return:
        """
        if self.run_finished:
            return

        payload = build_run_error_payload(error, extra=extra)
        previous = self.error_detail
        if previous is not None and previous.get('type') and not payload.get('type'):
            return
        if previous:
            for key in ('code', 'source'):
                if previous.get(key) is not None and key not in payload:
                    payload[key] = previous[key]
        self.error_message = str(payload.get('message') or '') or None
        self.error_detail = payload

    async def cancel(self, cancelled: RunCancelled) -> None:
        """
        持久化第一方取消的本轮增量消息

        :param cancelled: 第一方取消结果
        :return:
        """
        if self.run_finished:
            return
        await self.on_interrupted(list(cancelled.new_messages()))
        self.run_finished = True

    async def finalize(self, messages: list[ChatModelMessage]) -> None:
        """
        在底层流关闭后持久化失败或中断状态

        :param messages: 当前轮原生消息
        :return:
        """
        if self.run_finished:
            return
        try:
            if self.error_message is not None:
                await self.on_run_error(self.error_message, messages, self.error_detail)
            else:
                await self.on_interrupted(messages)
        finally:
            # 无论落库成败都标记结束，防止重复 finalize
            self.run_finished = True


async def _observe_native_events(
    *,
    event_stream: AsyncIterator[BaseEvent],
    message_history: Sequence[ChatModelMessage],
    run_id: str,
    lifecycle: StreamLifecycle,
    on_finish: Callable[[], Awaitable[None]] | None,
) -> AsyncIterator[BaseEvent]:
    """
    观察 Pydantic AI 原生事件并执行持久化生命周期回调

    :param event_stream: 官方协议事件流
    :param message_history: 传入模型的历史消息
    :param run_id: 当前 AG-UI 运行 ID
    :param lifecycle: 流式回调生命周期
    :param on_finish: 流结束回调
    :return:
    """
    current_run_messages: list[ChatModelMessage] = []
    try:
        try:
            with capture_run_messages() as captured_messages:
                try:
                    async for event in event_stream:
                        if isinstance(event, RunErrorEvent):
                            lifecycle.record_error(
                                event.message or '',
                                extra={
                                    **(event.raw_event if isinstance(event.raw_event, dict) else {}),
                                    'code': event.code,
                                    'source': 'run_error_event',
                                },
                            )
                        yield event
                finally:
                    aclose = getattr(event_stream, 'aclose', None)
                    if aclose is not None:
                        try:
                            await aclose()
                        except BaseException as exc:
                            # 清理失败不能覆盖模型异常，也不能阻止本轮消息落库
                            log.warning('关闭 Pydantic AI 事件流失败: {}', exc)
                    history_message_ids = {id(message) for message in message_history}
                    has_history_prefix = len(captured_messages) >= len(message_history) and all(
                        captured is historical or captured == historical
                        for captured, historical in zip(captured_messages, message_history, strict=False)
                    )
                    untagged_ids = (
                        {id(message) for message in captured_messages[len(message_history) :] if message.run_id is None}
                        if has_history_prefix
                        else set()
                    )
                    current_run_messages.extend(
                        message
                        for message in captured_messages[len(message_history) if has_history_prefix else 0 :]
                        if id(message) not in history_message_ids
                        and (message.run_id == run_id or id(message) in untagged_ids)
                    )
        except ValueError as exc:
            if 'created in a different Context' not in str(exc):
                raise
            log.warning('Pydantic AI 消息捕获上下文已在其他任务关闭: {}', exc)
        except Exception as exc:
            lifecycle.record_error(exc)
            raise
    finally:
        # 屏蔽取消：任务取消时仍完成落库/回调，避免状态与资源不一致
        with anyio.CancelScope(shield=True):
            try:
                await lifecycle.finalize(current_run_messages)
            finally:
                if on_finish:
                    await on_finish()


async def _produce_run_events(
    *,
    conversation_id: str,
    run: ActiveChatRun,
    encode_event: Callable[[BaseEvent], str],
    event_stream: AsyncIterator[BaseEvent],
    message_history: list[ChatModelMessage],
    lifecycle: StreamLifecycle,
    on_finish: Callable[[], Awaitable[None]] | None,
    deps: ChatAgentDeps,
) -> None:
    """
    在后台消费模型事件，不随 HTTP 断开取消

    :param conversation_id: 对话 ID
    :param run: 进行中的生成任务
    :param encode_event: 协议事件编码器
    :param event_stream: 官方协议事件流
    :param message_history: 传入模型的历史消息
    :param lifecycle: 流式回调生命周期
    :param on_finish: 流结束回调
    :param deps: 当前运行共享状态
    :return:
    """
    monitor_task = asyncio.create_task(
        monitor_shared_run(conversation_id=conversation_id, run=run),
        name=f'ai-chat-run-monitor-{conversation_id}',
    )
    observed_events = _observe_native_events(
        event_stream=event_stream,
        message_history=message_history,
        run_id=run.run_id,
        lifecycle=lifecycle,
        on_finish=on_finish,
    )
    terminal_event: str | None = None
    try:
        async for event in observed_events:
            if isinstance(event, RunFinishedEvent):
                event = (
                    event.model_copy(update={'result': {'status': 'interrupted'}})
                    if run.cancellation_token.cancelled
                    else event
                )
                run.publish(encode_ag_ui_event(StateSnapshotEvent(snapshot=deps.state)))
            part = getattr(event, 'part', None)
            content = getattr(part, 'content', None)
            cpu_heavy = (
                isinstance(part, FilePart)
                or isinstance(content, BinaryImage)
                or (isinstance(content, bytes | bytearray | memoryview) and len(content) >= 8 * 1024)
            )
            encoded_event = await asyncio.to_thread(encode_event, event) if cpu_heavy else encode_event(event)
            if isinstance(event, RunErrorEvent | RunFinishedEvent):
                terminal_event = encoded_event
            else:
                run.publish(encoded_event)
    except asyncio.CancelledError:
        run.cancellation_token.cancel()
    except Exception as exc:
        terminal_event = None
        lifecycle.record_error(exc)
        log.exception(f'后台聊天生成任务异常 conversation_id={conversation_id}: {exc}')
    finally:
        monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)
        try:
            await observed_events.aclose()
        except BaseException as exc:
            lifecycle.record_error(exc)
            log.exception(f'关闭后台聊天事件流异常 conversation_id={conversation_id}: {exc}')
        # 终止事件在消息和协议状态保存后发布，避免客户端立即刷新读到旧快照
        run.publish(
            terminal_event or encode_ag_ui_event(RunErrorEvent(message=lifecycle.error_message or '对话事件流意外结束'))
        )
        await finish_run(conversation_id=conversation_id, run=run)


async def _persist_run_state(
    *,
    conversation_id: str,
    adapter: BuddyAGUIAdapter,
    deps: ChatAgentDeps,
    on_finish: Callable[[], Awaitable[None]] | None,
) -> None:
    """在消息落库后保存协议状态并释放供应商资源

    :param conversation_id: 对话 ID
    :param adapter: 当前协议运行适配器
    :param deps: 当前运行共享状态
    :param on_finish: 资源释放回调
    :return:
    """
    try:
        async with async_db_session.begin() as db:
            rows = await ai_buddy_message_dao.get_history_page(db, conversation_id, before=None, limit=1)
            if rows and rows[0].role == 'assistant':
                await ai_buddy_message_dao.update(
                    db,
                    rows[0].id,
                    {
                        'turn_context': {
                            **(rows[0].turn_context or {}),
                            'lifecycle_events': adapter.lifecycle_events,
                            'agent_state': deps.state,
                            'ag_ui_activities': [
                                activity.model_dump(mode='json', by_alias=True)
                                for activity in adapter.activities.values()
                            ],
                        }
                    },
                )
    except Exception as exc:
        log.exception(f'保存运行状态失败 conversation_id={conversation_id}: {exc}')
    finally:
        if on_finish:
            await on_finish()


async def build_streaming_response(
    *,
    user_id: int,
    agent: ChatAgent,
    run_input: RunAgentInput,
    accept: str | None,
    message_history: list[ChatModelMessage],
    on_complete: Callable[[AgentRunResult[Any]], Awaitable[None]],
    on_run_error: Callable[[str, list[ChatModelMessage], dict[str, Any] | None], Awaitable[None]],
    on_interrupted: Callable[[list[ChatModelMessage]], Awaitable[None]],
    on_finish: Callable[[], Awaitable[None]] | None = None,
    conversation_id: str | None = None,
    run_timeout: float | None = None,
) -> StreamingResponse:
    """
    通过官方 AG-UI 适配器运行代理并返回流式响应

    :param user_id: 用户 ID
    :param agent: 聊天代理
    :param run_input: 运行参数
    :param accept: Accept 请求头
    :param message_history: 消息历史
    :param on_complete: 完成回调
    :param on_run_error: 运行失败回调
    :param on_interrupted: 运行中断回调
    :param on_finish: 流结束回调
    :param conversation_id: 对话 ID，用于后台任务登记
    :param run_timeout: 本轮执行时限，单位秒
    :return:
    """
    resolved_conversation_id = conversation_id or run_input.thread_id
    run_id = run_input.run_id
    active_run = await register_run(conversation_id=resolved_conversation_id, run_id=run_id)
    claimed = False
    try:
        frontend_tool_results = build_frontend_tool_results(run_input=run_input, message_history=message_history)
        # 数据库已包含当前轮消息时，避免再次叠加客户端历史
        stream_run_input = (
            run_input.model_copy(update={'messages': []}) if message_history and run_input.messages else run_input
        )
        deps = ChatAgentDeps(user_id=user_id, conversation_id=resolved_conversation_id)
        adapter = BuddyAGUIAdapter(
            agent=agent,
            run_input=stream_run_input,
            accept=accept,
            allow_uploaded_files=True,
            preserve_file_data=True,
            deps=deps,
        )
        deferred_tool_results = adapter.deferred_tool_results
        if frontend_tool_results is not None:
            if deferred_tool_results is not None:
                frontend_tool_results.update(deferred_tool_results)
            deferred_tool_results = frontend_tool_results

        async def complete(result: AgentRunResult[Any]) -> None:
            """标记前端工具请求后执行生成完成回调

            :param result: 执行结果
            :return:
            """
            mark_frontend_tool_requests(result=result, tools=stream_run_input.tools)
            await on_complete(result)

        lifecycle = StreamLifecycle(
            on_complete=complete,
            on_run_error=on_run_error,
            on_interrupted=on_interrupted,
        )
        event_stream_handler = adapter.build_event_stream()
        response_headers = dict(event_stream_handler.response_headers or {})
        claimed = await shared_chat_run_store.claim(
            conversation_id=resolved_conversation_id,
            run_id=run_id,
        )
        if not claimed:
            raise errors.ConflictError(msg='当前对话正在生成，请稍后再试')
        if deferred_tool_results is not None and deferred_tool_results.approvals:
            await ai_buddy_approval_audit_service.resolve_work(
                user_id=user_id,
                conversation_id=resolved_conversation_id,
                decisions={
                    call_id: value is True or isinstance(value, ToolApproved)
                    for call_id, value in deferred_tool_results.approvals.items()
                },
            )
        event_stream = adapter.run_stream(
            deps=deps,
            message_history=message_history,
            deferred_tool_results=deferred_tool_results,
            conversation_id=resolved_conversation_id,
            run_id=run_id,
            cancellation_token=active_run.cancellation_token,
            timeout=run_timeout,
            instructions=(
                'AG-UI 客户端提供的上下文：\n'
                + json.dumps(
                    [context.model_dump(mode='json') for context in stream_run_input.context],
                    ensure_ascii=False,
                )
                if stream_run_input.context
                else None
            ),
            on_complete=lifecycle.complete,
            on_cancel=lifecycle.cancel,
        )
    except BaseException:
        if claimed:
            await shared_chat_run_store.release(
                conversation_id=resolved_conversation_id,
                run_id=run_id,
            )
        discard_run(resolved_conversation_id, active_run)
        raise

    active_run.configure_stream(media_type=event_stream_handler.content_type, headers=response_headers)
    active_run.start(
        _produce_run_events(
            conversation_id=resolved_conversation_id,
            run=active_run,
            encode_event=event_stream_handler.encode_event,
            event_stream=event_stream,
            message_history=message_history,
            lifecycle=lifecycle,
            on_finish=partial(
                _persist_run_state,
                conversation_id=resolved_conversation_id,
                adapter=adapter,
                deps=deps,
                on_finish=on_finish,
            ),
            deps=deps,
        ),
        conversation_id=resolved_conversation_id,
    )
    return build_run_stream_response(active_run)
