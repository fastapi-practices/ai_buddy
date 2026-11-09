import asyncio

from typing import Any

import anyio

from ag_ui.core import RunAgentInput, RunErrorEvent, RunFinishedEvent, StateSnapshotEvent
from pydantic_ai import AgentRunResult, capture_run_messages
from pydantic_ai.messages import ModelMessage

from backend.common.log import log
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.durability.recovery import RecoveryContext
from backend.plugin.ai_buddy.agent.work.ag_ui import BuddyAGUIAdapter
from backend.plugin.ai_buddy.agent.work.persistence import (
    extract_assistant_messages,
    extract_assistant_run_messages,
    persist_completion,
    persist_terminal_completion,
)
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store
from backend.plugin.ai_buddy.agent.work.runs import ActiveChatRun
from backend.plugin.ai_buddy.agent.work.session_factory import open_chat_session
from backend.plugin.ai_buddy.agent.work.stream import StreamLifecycle
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.dataclasses import ChatAgentDeps, CompletionPersistenceContext
from backend.plugin.ai_buddy.enums import AIBuddyMessageStatus, AIBuddyOrigin
from backend.plugin.ai_buddy.schema.chat import parse_forwarded_props
from backend.plugin.ai_buddy.utils.ag_ui import encode_ag_ui_event


def _build_lifecycle(persistence: CompletionPersistenceContext) -> StreamLifecycle:
    """
    构建本轮流式生命周期回调，负责把运行终态写回助手消息

    :param persistence: 消息落库上下文
    :return:
    """

    async def on_complete(result: AgentRunResult[Any]) -> None:
        """
        保存本轮生成完成后的助手消息

        :param result: 执行结果
        :return:
        """
        async with async_db_session.begin() as db:
            await persist_completion(
                db=db,
                persistence=persistence,
                messages=extract_assistant_run_messages(result),
            )

    async def on_run_error(
        message: str,
        messages: list[Any],
        detail: dict[str, Any] | None = None,
    ) -> None:
        """
        将本轮助手消息保存为错误终态

        :param message: 消息内容
        :param messages: 消息列表
        :param detail: 详细信息
        :return:
        """
        await persist_terminal_completion(
            persistence=persistence,
            messages=extract_assistant_messages(messages),
            status=AIBuddyMessageStatus.error,
            reason=message,
            detail=detail,
        )

    async def on_interrupted(messages: list[Any]) -> None:
        """
        将本轮助手消息保存为中断终态

        :param messages: 消息列表
        :return:
        """
        await persist_terminal_completion(
            persistence=persistence,
            messages=extract_assistant_messages(messages),
            status=AIBuddyMessageStatus.interrupted,
        )

    return StreamLifecycle(
        on_complete=on_complete,
        on_run_error=on_run_error,
        on_interrupted=on_interrupted,
    )


async def _publish_events(
    *,
    conversation_id: str,
    run: ActiveChatRun,
    encode_event: Any,
    event_stream: Any,
    message_history: list[ModelMessage],
    lifecycle: StreamLifecycle,
    deps: ChatAgentDeps,
) -> None:
    """
    消费协议事件并写入 Redis 事件日志

    :param conversation_id: 对话 ID
    :param run: 当前运行句柄
    :param encode_event: 协议事件编码器
    :param event_stream: 协议事件流
    :param message_history: 传入模型的历史消息
    :param lifecycle: 流式回调生命周期
    :param deps: 当前运行共享状态
    :return:
    """
    terminal_event: str | None = None
    current_run_messages: list[Any] = []
    try:
        try:
            with capture_run_messages() as captured_messages:
                try:
                    async for event in event_stream:
                        if isinstance(event, RunFinishedEvent):
                            await run.publish(encode_ag_ui_event(StateSnapshotEvent(snapshot=deps.state)))
                        encoded = encode_event(event)
                        if isinstance(event, RunErrorEvent | RunFinishedEvent):
                            terminal_event = encoded
                        else:
                            await run.publish(encoded)
                finally:
                    aclose = getattr(event_stream, 'aclose', None)
                    if aclose is not None:
                        try:
                            await aclose()
                        except BaseException as exc:
                            log.warning(f'关闭容灾事件流失败: {exc}')
                    history_ids = {id(message) for message in message_history}
                    current_run_messages.extend(
                        message for message in captured_messages if id(message) not in history_ids
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            lifecycle.record_error(exc)
            log.exception(f'容灾恢复事件流异常 conversation_id={conversation_id}: {exc}')
    finally:
        # 屏蔽取消：任务取消时仍完成落库，避免助手消息停留在 pending
        with anyio.CancelScope(shield=True):
            try:
                await lifecycle.finalize(current_run_messages)
            finally:
                fallback = encode_ag_ui_event(RunErrorEvent(message=lifecycle.error_message or '对话事件流意外结束'))
                await run.publish(terminal_event or fallback)


async def _mark_interrupted(*, message_id: int) -> None:
    """
    把恢复失败的助手消息收敛为中断

    :param message_id: 助手消息 ID
    :return:
    """
    try:
        async with async_db_session.begin() as db:
            await ai_buddy_message_dao.update_pending(
                db,
                message_id,
                {'status': AIBuddyMessageStatus.interrupted},
            )
    except Exception as exc:
        log.warning(f'收敛容灾恢复失败消息异常 message_id={message_id}: {exc}')


async def resume_interrupted_run(*, context: RecoveryContext, run_id: str) -> bool:
    """
    从步骤快照续跑被中断的对话生成

    :param context: 恢复上下文
    :param run_id: 恢复运行的运行 ID
    :return:
    """
    conversation_id = context.conversation_id
    agent_session = None
    try:
        forwarded_props = parse_forwarded_props(context.forwarded_props)
        origin = AIBuddyOrigin(context.origin)
    except ValueError as exc:
        log.warning(f'容灾恢复参数解析失败 conversation_id={conversation_id}: {exc}')
        return False

    succeeded = False
    try:
        async with async_db_session() as db:
            agent_session, agent = await open_chat_session(
                db=db,
                forwarded_props=forwarded_props,
                is_superuser=context.is_superuser,
                user_id=context.user_id,
                conversation_id=conversation_id,
                origin=origin,
            )
        deps = ChatAgentDeps(user_id=context.user_id, conversation_id=conversation_id)
        adapter = BuddyAGUIAdapter(
            agent=agent,
            run_input=RunAgentInput(thread_id=conversation_id, run_id=run_id, messages=[], tools=[], context=[]),
            allow_uploaded_files=True,
            preserve_file_data=True,
            deps=deps,
        )
        event_stream_handler = adapter.build_event_stream()
        await shared_chat_run_store.set_event_log_meta(
            conversation_id=conversation_id,
            run_id=run_id,
            media_type=event_stream_handler.content_type,
            headers=dict(event_stream_handler.response_headers or {}),
        )
        persistence = CompletionPersistenceContext(
            conversation_id=conversation_id,
            user_id=context.user_id,
            forwarded_props=forwarded_props,
            title=context.title,
            assistant_message_id=context.assistant_message_id,
        )
        lifecycle = _build_lifecycle(persistence)
        event_stream = adapter.run_stream(
            deps=deps,
            message_history=context.message_history,
            conversation_id=conversation_id,
            run_id=run_id,
            on_complete=lifecycle.complete,
            on_cancel=lifecycle.cancel,
        )
        run = ActiveChatRun(run_id=run_id, conversation_id=conversation_id)
        await _publish_events(
            conversation_id=conversation_id,
            run=run,
            encode_event=event_stream_handler.encode_event,
            event_stream=event_stream,
            message_history=context.message_history,
            lifecycle=lifecycle,
            deps=deps,
        )
        log.info(f'容灾恢复已完成 conversation_id={conversation_id}')
        succeeded = True
    except Exception as exc:
        log.exception(f'容灾恢复失败 conversation_id={conversation_id}: {exc}')
        await _mark_interrupted(message_id=context.assistant_message_id)
    finally:
        try:
            await shared_chat_run_store.close_event_log(conversation_id=conversation_id, run_id=run_id)
            await shared_chat_run_store.release(conversation_id=conversation_id, run_id=run_id)
        except Exception as exc:
            log.warning(f'释放容灾恢复租约失败 conversation_id={conversation_id}: {exc}')
        if agent_session is not None:
            try:
                await agent_session.aclose()
            except Exception as exc:
                log.warning(f'关闭模型供应商客户端失败: {exc}')
    return succeeded
