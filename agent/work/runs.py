from __future__ import annotations

import asyncio
import time

from contextlib import suppress
from typing import TYPE_CHECKING, Any

from pydantic_ai import CancellationToken
from starlette.responses import StreamingResponse

from backend.common.exception import errors
from backend.common.log import log
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Coroutine

_LEASE_HEARTBEAT_INTERVAL_SECONDS = 5.0
_CANCEL_POLL_INTERVAL_SECONDS = 1.0
_SSE_HEADERS = {'X-Accel-Buffering': 'no', 'Cache-Control': 'no-cache'}


class ActiveChatRun:
    """当前进程持有的对话生成句柄"""

    def __init__(self, *, run_id: str, conversation_id: str | None = None) -> None:
        """
        初始化本进程生成任务及事件流状态

        :param run_id: 运行 ID
        :param conversation_id: 对话 ID
        :return:
        """
        self.run_id = run_id
        self.conversation_id = conversation_id
        self.cancellation_token = CancellationToken()
        self.task: asyncio.Task[None] | None = None
        self._activation = asyncio.Event()
        self._log_chain: asyncio.Task[None] | None = None
        self.media_type = 'text/event-stream'
        self.headers = dict(_SSE_HEADERS)

    def configure_stream(self, *, media_type: str, headers: dict[str, str] | None = None) -> None:
        """
        记录本轮流的媒体类型和响应头，重连时复用

        :param media_type: SSE Content-Type
        :param headers: 额外响应头
        :return:
        """
        self.media_type = media_type
        merged = dict(_SSE_HEADERS)
        if headers:
            merged.update(headers)
        self.headers = merged
        if self.conversation_id:
            self._log_chain = asyncio.create_task(self._write_log_meta(self._log_chain))

    @property
    def is_activated(self) -> bool:
        """任务是否已允许执行"""
        return self._activation.is_set()

    def start(self, coroutine: Coroutine[Any, Any, None], *, conversation_id: str) -> None:
        """
        幂等启动后台生成任务

        :param coroutine: 后台生成协程
        :param conversation_id: 对话 ID
        :return:
        """
        if self.task is not None:
            coroutine.close()
            return
        self.task = asyncio.create_task(
            self._run_after_activation(coroutine),
            name=f'ai-chat-run-{conversation_id}',
        )

    def activate(self) -> None:
        """在业务事务提交后允许后台生成开始"""
        self._activation.set()

    def publish(self, event: str) -> None:
        """
        将已编码协议事件写入 Redis Stream

        :param event: 已编码协议事件
        :return:
        """
        if self.conversation_id:
            self._log_chain = asyncio.create_task(self._write_log_event(self._log_chain, event))

    async def _write_log_meta(self, previous: asyncio.Task[None] | None) -> None:
        """
        在前序日志任务完成后写入流元信息

        :param previous: 前序日志任务
        :return:
        """
        if previous is not None:
            with suppress(Exception):
                await previous
        try:
            await shared_chat_run_store.set_event_log_meta(
                conversation_id=self.conversation_id or '',
                run_id=self.run_id,
                media_type=self.media_type,
                headers=dict(self.headers),
            )
        except Exception as exc:
            log.warning(f'写入聊天事件流元信息失败 conversation_id={self.conversation_id}: {exc}')

    async def _write_log_event(self, previous: asyncio.Task[None] | None, event: str) -> None:
        """
        在前序日志任务完成后追加协议事件

        :param previous: 前序日志任务
        :param event: 已编码协议事件
        :return:
        """
        if previous is not None:
            with suppress(Exception):
                await previous
        try:
            await shared_chat_run_store.append_event(conversation_id=self.conversation_id or '', payload=event)
        except Exception as exc:
            log.warning(f'写入聊天事件日志失败 conversation_id={self.conversation_id}: {exc}')

    async def drain_event_log(self) -> None:
        """等待已排队的事件日志写完"""
        chain = self._log_chain
        if chain is not None:
            with suppress(Exception):
                await chain

    async def cancel_before_activation(self) -> None:
        """取消尚未越过事务提交屏障的任务"""
        if self.task is None:
            return
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    async def _run_after_activation(self, coroutine: Coroutine[Any, Any, None]) -> None:
        """
        等待响应激活后启动生成并回收未执行协程

        :param coroutine: 后台协程
        :return:
        """
        try:
            await self._activation.wait()
        except asyncio.CancelledError:
            coroutine.close()
            raise
        await coroutine


_runs: dict[str, ActiveChatRun] = {}


def get_local_run(conversation_id: str) -> ActiveChatRun | None:
    """
    获取当前进程持有的生成句柄

    :param conversation_id: 对话 ID
    :return:
    """
    run = _runs.get(conversation_id)
    if run is not None and run.task is not None and run.task.done():
        _runs.pop(conversation_id, None)
        return None
    return run


async def register_run(*, conversation_id: str, run_id: str) -> ActiveChatRun:
    """
    注册当前进程持有的生成句柄

    :param conversation_id: 对话 ID
    :param run_id: 运行 ID
    :return:
    """
    existing = get_local_run(conversation_id)
    if existing is not None:
        if await shared_chat_run_store.is_active(conversation_id=conversation_id):
            raise errors.ConflictError(msg='当前对话正在生成，请稍后再试')
        if existing.is_activated:
            existing.cancellation_token.cancel()
        else:
            await existing.cancel_before_activation()
        _runs.pop(conversation_id, None)
    run = ActiveChatRun(run_id=run_id, conversation_id=conversation_id)
    _runs[conversation_id] = run
    return run


def discard_run(conversation_id: str, run: ActiveChatRun) -> None:
    """
    移除当前进程的生成句柄

    :param conversation_id: 对话 ID
    :param run: 待移除的生成句柄
    :return:
    """
    if _runs.get(conversation_id) is run:
        _runs.pop(conversation_id, None)


async def has_active_run(conversation_id: str) -> bool:
    """
    根据共享租约判断对话是否正在生成

    :param conversation_id: 对话 ID
    :return:
    """
    return await shared_chat_run_store.is_active(conversation_id=conversation_id)


async def request_stop_run(conversation_id: str) -> bool:
    """
    请求当前执行者停止对话生成

    :param conversation_id: 对话 ID
    :return:
    """
    run = get_local_run(conversation_id)
    local_requested = run is not None
    if run is not None:
        run.cancellation_token.cancel()
    try:
        shared_requested = await shared_chat_run_store.request_cancel(conversation_id=conversation_id)
    except Exception:
        if local_requested:
            return True
        raise
    return shared_requested or local_requested


async def wait_run_stopped(
    conversation_id: str,
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.1,
) -> bool:
    """
    等待对话生成租约释放

    :param conversation_id: 对话 ID
    :param timeout: 最大等待秒数
    :param poll_interval: 轮询间隔秒数
    :return:
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while await has_active_run(conversation_id):
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(poll_interval, remaining))
    return True


def activate_run(conversation_id: str) -> None:
    """
    在业务事务提交后启动已准备的生成任务

    :param conversation_id: 对话 ID
    :return:
    """
    run = get_local_run(conversation_id)
    if run is None:
        raise RuntimeError('聊天生成任务不存在')
    run.activate()


async def abort_prepared_run(conversation_id: str) -> bool:
    """
    释放当前进程中尚未启动的生成任务

    :param conversation_id: 对话 ID
    :return:
    """
    run = get_local_run(conversation_id)
    if run is None or run.is_activated:
        return False
    discard_run(conversation_id, run)
    await run.cancel_before_activation()
    await shared_chat_run_store.reset_event_log(conversation_id=conversation_id)
    return await shared_chat_run_store.release(conversation_id=conversation_id, run_id=run.run_id)


async def monitor_shared_run(*, conversation_id: str, run: ActiveChatRun) -> None:
    """
    续期共享租约并接收跨进程取消信号

    :param conversation_id: 对话 ID
    :param run: 当前进程持有的生成句柄
    :return:
    """
    next_heartbeat = 0.0
    while True:
        now = time.monotonic()
        try:
            state = await shared_chat_run_store.poll(
                conversation_id=conversation_id,
                run_id=run.run_id,
                renew=now >= next_heartbeat,
            )
        except Exception as exc:
            log.warning(f'聊天任务协调状态读取失败 conversation_id={conversation_id}: {exc}')
            run.cancellation_token.cancel()
            return
        if state != 2:
            run.cancellation_token.cancel()
            return
        if now >= next_heartbeat:
            next_heartbeat = now + _LEASE_HEARTBEAT_INTERVAL_SECONDS
        await asyncio.sleep(_CANCEL_POLL_INTERVAL_SECONDS)


async def finish_run(*, conversation_id: str, run: ActiveChatRun) -> None:
    """
    关闭 Redis Stream 并释放租约

    :param conversation_id: 对话 ID
    :param run: 当前进程持有的生成句柄
    :return:
    """
    try:
        await run.drain_event_log()
        await shared_chat_run_store.close_event_log(conversation_id=conversation_id, run_id=run.run_id)
        await shared_chat_run_store.release(conversation_id=conversation_id, run_id=run.run_id)
    except Exception as exc:
        log.exception(f'完成共享聊天任务状态失败 conversation_id={conversation_id}: {exc}')
    finally:
        discard_run(conversation_id, run)


def build_run_stream_response(run: ActiveChatRun) -> StreamingResponse:
    """
    从 Redis Stream 订阅本轮生成事件

    :param run: 当前进程持有的生成句柄
    :return:
    """
    conversation_id = run.conversation_id
    if not conversation_id:
        raise RuntimeError('聊天生成任务缺少对话 ID')
    return StreamingResponse(
        _replay_event_log(conversation_id),
        media_type=run.media_type,
        headers=dict(run.headers),
    )


async def _replay_event_log(conversation_id: str, after_id: str = '0-0') -> AsyncIterator[str]:
    """
    重放已持久化事件并等待后续事件，每个事件带 SSE id 供客户端断线续传

    :param conversation_id: 对话 ID
    :param after_id: 已收到的最后一个事件 ID，从其后开始重放
    :return:
    """
    last_id = after_id
    while True:
        try:
            batch = await shared_chat_run_store.read_events(conversation_id=conversation_id, after_id=last_id)
            if batch:
                for event_id, payload in batch:
                    last_id = event_id
                    yield f'id: {event_id}\n{payload}'
                continue
            meta = await shared_chat_run_store.get_event_log_meta(conversation_id=conversation_id)
            if meta and meta.get('closed'):
                leftover = await shared_chat_run_store.read_events(conversation_id=conversation_id, after_id=last_id)
                for event_id, payload in leftover:
                    last_id = event_id
                    yield f'id: {event_id}\n{payload}'
                return
            live = await shared_chat_run_store.listen_events(conversation_id=conversation_id, after_id=last_id)
            if live:
                for event_id, payload in live:
                    last_id = event_id
                    yield f'id: {event_id}\n{payload}'
                continue
            if not await has_active_run(conversation_id) and not await shared_chat_run_store.has_event_log(
                conversation_id=conversation_id
            ):
                return
        except Exception as exc:
            log.warning(f'读取聊天事件日志失败 conversation_id={conversation_id}: {exc}')
        yield ': keepalive\n\n'


async def attach_event_stream(*, conversation_id: str, after_id: str = '0-0') -> StreamingResponse:
    """
    从 Redis Stream 重放并继续订阅当前对话生成流

    :param conversation_id: 对话 ID
    :param after_id: 已收到的最后一个事件 ID，从其后开始重放
    :return:
    """
    run = get_local_run(conversation_id)
    meta = await shared_chat_run_store.get_event_log_meta(conversation_id=conversation_id)
    if (
        meta is not None
        or await shared_chat_run_store.has_event_log(conversation_id=conversation_id)
        or run is not None
        or await has_active_run(conversation_id)
    ):
        media_type = run.media_type if run else 'text/event-stream'
        headers = dict(run.headers if run else _SSE_HEADERS)
        if run is None and meta:
            media_type = str(meta.get('media_type') or media_type)
            raw_headers = meta.get('headers')
            if isinstance(raw_headers, dict):
                headers.update({str(key): str(value) for key, value in raw_headers.items()})
        return StreamingResponse(_replay_event_log(conversation_id, after_id), media_type=media_type, headers=headers)
    return StreamingResponse(iter(()), media_type='text/event-stream', headers=dict(_SSE_HEADERS))


async def shutdown_runs(*, timeout: float = 10.0) -> None:
    """
    停止本进程所有聊天任务并等待终态落库

    :param timeout: 优雅停止最大等待秒数
    :return:
    """
    runs = list(_runs.items())
    if not runs:
        return
    active_tasks: list[asyncio.Task[None]] = []
    for conversation_id, run in runs:
        if run.is_activated:
            run.cancellation_token.cancel()
            if run.task is not None:
                active_tasks.append(run.task)
        else:
            await run.cancel_before_activation()
            try:
                await shared_chat_run_store.release(conversation_id=conversation_id, run_id=run.run_id)
            except Exception as exc:
                log.warning(f'关闭聊天任务时释放租约失败 conversation_id={conversation_id}: {exc}')
            discard_run(conversation_id, run)
    if not active_tasks:
        return
    _, pending = await asyncio.wait(active_tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
