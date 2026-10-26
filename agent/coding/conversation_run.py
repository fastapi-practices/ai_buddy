from __future__ import annotations

import asyncio
import contextlib

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic_ai.exceptions import RunTimedOut
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserContent, UserPromptPart

from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.coding.approvals import wait_for_approval
from backend.plugin.ai_buddy.agent.coding.events import CodingEventStream
from backend.plugin.ai_buddy.agent.coding.execution_bridge import close_owned_bridge as close_owned_execution_bridge
from backend.plugin.ai_buddy.agent.coding.protocol.acp.bridge import close_owned_bridge
from backend.plugin.ai_buddy.agent.coding.session import open_coding_session
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store
from backend.plugin.ai_buddy.agent.work.runs import (
    ActiveChatRun,
    build_run_stream_response,
    discard_run,
    finish_run,
    monitor_shared_run,
    register_run,
)
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType, AIBuddyMessageRole, AIBuddyMessageStatus
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.utils.media_store import dump_model_message_payloads, encode_model_message_payloads
from backend.plugin.ai_buddy.utils.run_error import build_run_error_payload

if TYPE_CHECKING:
    from starlette.responses import StreamingResponse

    from backend.plugin.ai_buddy.agent.coding.types import AgentMessage, AgentToolCall
    from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam


async def run_conversation_coding(
    *,
    user_id: int,
    conversation_id: str,
    prompt: str,
    forwarded_props: AIBuddyChatForwardedPropsParam,
    assistant_message_id: int,
    run_id: str | None = None,
) -> StreamingResponse:
    """
    在同一对话上后台跑编码轮，HTTP 只订阅事件

    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :param prompt: 本轮用户输入
    :param forwarded_props: 聊天扩展参数
    :param assistant_message_id: 占位助手消息 ID
    :param run_id: 提交时确定的运行 ID
    :return:
    """
    if forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        raise errors.RequestError(msg='编码模式仅支持文本对话')
    run_id = run_id or uuid4().hex
    active_run = await register_run(conversation_id=conversation_id, run_id=run_id)
    claimed = await shared_chat_run_store.claim(conversation_id=conversation_id, run_id=run_id)
    if not claimed:
        discard_run(conversation_id, active_run)
        raise errors.ConflictError(msg='当前对话正在生成，请稍后再试')
    active_run.configure_stream(media_type='text/event-stream')
    active_run.start(
        _produce_coding_run(
            user_id=user_id,
            conversation_id=conversation_id,
            prompt=prompt,
            forwarded_props=forwarded_props,
            assistant_message_id=assistant_message_id,
            run=active_run,
        ),
        conversation_id=conversation_id,
    )
    return build_run_stream_response(active_run)


async def _produce_coding_run(  # ruff: ignore[complex-structure]
    *,
    user_id: int,
    conversation_id: str,
    prompt: str,
    forwarded_props: AIBuddyChatForwardedPropsParam,
    assistant_message_id: int,
    run: ActiveChatRun,
) -> None:
    """
    后台消费编码事件，不随 HTTP 断开取消

    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :param prompt: 本轮用户输入
    :param forwarded_props: 聊天扩展参数
    :param assistant_message_id: 占位助手消息 ID
    :param run: 当前进程持有的生成句柄
    :return:
    """
    monitor_task = asyncio.create_task(
        monitor_shared_run(conversation_id=conversation_id, run=run),
        name=f'ai-coding-run-monitor-{conversation_id}',
    )
    session = None
    chunks: list[str] = []
    model_messages: list[ModelMessage] = []
    stream = CodingEventStream(
        conversation_id=conversation_id, run_id=run.run_id, message_id=f'msg_{assistant_message_id}'
    )
    run.publish(stream.encode('start', {}))

    async def emit(event: str, data: dict[str, Any]) -> None:  # ruff: ignore[unused-async]
        """发布本轮运行的界面事件

        :param event: 事件数据
        :param data: 输入数据
        :return:
        """
        if event == 'text':
            delta = str(data.get('delta') or data.get('text') or '')
            if delta:
                chunks.append(delta)
        run.publish(stream.encode(event, data))

    async def persist_message(message: AgentMessage) -> None:
        """保存编码运行产生的助手消息

        :param message: 消息内容
        :return:
        """
        if message.model_messages:
            model_messages[:] = message.model_messages
        if message.role != AIBuddyMessageRole.assistant or not message.content:
            return
        if not chunks:
            chunks.append(message.content)
        await _write_assistant_message(
            assistant_message_id=assistant_message_id,
            conversation_id=conversation_id,
            model_messages=model_messages,
            text=''.join(chunks).strip(),
            status=AIBuddyMessageStatus.pending,
            pending_only=True,
        )

    async def is_cancelled() -> bool:  # ruff: ignore[unused-async]
        """读取当前生成任务的取消状态"""
        return run.cancellation_token.cancelled

    async def wait_approval(_reason: str, call: AgentToolCall) -> bool:
        """等待本轮工具调用的用户审批

        :param call: 工具调用
        :return:
        """
        return await wait_for_approval(
            conversation_id=conversation_id,
            user_id=user_id,
            run_id=run.run_id,
            call=call,
            emit=emit,
            is_cancelled=is_cancelled,
        )

    producer = asyncio.current_task()

    async def watch_cancel() -> None:
        # CancellationToken 无异步等待接口，轮询同时覆盖宿主初始化阶段
        """监控取消信号并停止后台生成"""
        while not run.cancellation_token.cancelled:  # ruff: ignore[async-busy-wait]
            await asyncio.sleep(0.1)
        if producer is not None:
            producer.cancel()

    cancel_task = asyncio.create_task(watch_cancel())

    try:
        async with async_db_session() as db:
            conversation = await ai_buddy_conversation_service.get_owned_conversation(
                db=db,
                conversation_id=conversation_id,
                user_id=user_id,
                must_exist=True,
            )
            state = await ai_buddy_conversation_service.get_chat_state(
                db=db, conversation_id=conversation_id, user_id=user_id, must_exist=True
            )
            # 当前用户输入与待生成消息已落库，本轮提示由宿主单独传入
            history_end = 0
            user_content: list[UserContent] = []
            for index, row in enumerate(state.message_rows):
                if row.id == assistant_message_id and index > 0:
                    history_end, input_end = state.row_model_message_ranges[index - 1]
                    for message in state.model_messages[history_end:input_end]:
                        if isinstance(message, ModelRequest):
                            for part in message.parts:
                                if isinstance(part, UserPromptPart):
                                    user_content.extend(
                                        [part.content] if isinstance(part.content, str) else part.content
                                    )
                    break
            session = await open_coding_session(
                db=db,
                user_id=user_id,
                conversation_id=conversation_id,
                run_id=run.run_id,
                forwarded_props=forwarded_props,
                permission_mode=forwarded_props.permission_mode,
                project_id=conversation.project_id,
                goal=conversation.goal,
                message_history=state.model_messages[:history_end],
                user_content=user_content,
            )
        status, _ = await asyncio.wait_for(
            session.run(
                prompt=prompt,
                emit=emit,
                persist_message=persist_message,
                is_cancelled=is_cancelled,
                wait_approval=wait_approval,
            ),
            timeout=settings.AI_BUDDY_AGENT_SANDBOX_TIMEOUT_MINUTES * 60,
        )
        if run.cancellation_token.cancelled:
            status = AIBuddyMessageStatus.interrupted
        text = ''.join(chunks).strip()
        await _write_assistant_message(
            assistant_message_id=assistant_message_id,
            conversation_id=conversation_id,
            model_messages=model_messages,
            text=text,
            status=status,
        )
        run.publish(stream.encode('done', {'status': status}))
    except asyncio.CancelledError:
        cancel_task.cancel()
        run.cancellation_token.cancel()
        await _write_assistant_message(
            assistant_message_id=assistant_message_id,
            conversation_id=conversation_id,
            model_messages=model_messages,
            text=''.join(chunks).strip(),
            status=AIBuddyMessageStatus.interrupted,
        )
        run.publish(stream.encode('done', {'status': AIBuddyMessageStatus.interrupted}))
        raise
    except (TimeoutError, RunTimedOut):
        await _write_assistant_message(
            assistant_message_id=assistant_message_id,
            conversation_id=conversation_id,
            model_messages=model_messages,
            text=''.join(chunks).strip() or '编码运行超时',
            status=AIBuddyMessageStatus.timeout,
        )
        run.publish(stream.encode('error', {'message': '编码运行超时', 'code': 'run_timeout'}))
    except Exception as exc:
        log.exception(f'后台编码任务异常 conversation_id={conversation_id}: {exc}')
        payload = build_run_error_payload(exc)
        await _write_assistant_message(
            assistant_message_id=assistant_message_id,
            conversation_id=conversation_id,
            model_messages=model_messages,
            text=''.join(chunks).strip() or payload['message'],
            status=AIBuddyMessageStatus.error,
        )
        run.publish(stream.encode('error', payload))
    finally:
        monitor_task.cancel()
        cancel_task.cancel()
        await asyncio.gather(monitor_task, cancel_task, return_exceptions=True)
        try:
            if session is not None:
                await asyncio.wait_for(session.aclose(), timeout=10)
        finally:
            bridge_id = getattr(forwarded_props, 'acp_bridge_id', None)
            if bridge_id:
                with contextlib.suppress(Exception):
                    await close_owned_bridge(bridge_id=bridge_id, user_id=user_id, conversation_id=conversation_id)
            execution_bridge_id = getattr(forwarded_props, 'execution_bridge_id', None)
            if execution_bridge_id:
                with contextlib.suppress(Exception):
                    await close_owned_execution_bridge(
                        bridge_id=execution_bridge_id, user_id=user_id, conversation_id=conversation_id
                    )
            try:
                if stream.activities:
                    async with async_db_session.begin() as db:
                        message = await ai_buddy_message_dao.get(db, assistant_message_id)
                        if message is not None:
                            await ai_buddy_message_dao.update(
                                db,
                                assistant_message_id,
                                {
                                    'turn_context': {
                                        **(message.turn_context or {}),
                                        'ag_ui_activities': list(stream.activities.values()),
                                    },
                                },
                            )
            finally:
                await finish_run(conversation_id=conversation_id, run=run)


async def _write_assistant_message(
    *,
    assistant_message_id: int,
    conversation_id: str,
    text: str,
    status: str,
    pending_only: bool = False,
    model_messages: list[ModelMessage] | None = None,
) -> None:
    """更新编码回复及对应模型消息

    :param assistant_message_id: 助手消息 ID
    :param conversation_id: 对话 ID
    :param text: 文本内容
    :param status: 状态值
    :param pending_only: 是否仅更新待处理消息
    :param model_messages: 模型消息列表
    :return:
    """
    if pending_only and not text:
        return
    payload = await dump_model_message_payloads(model_messages or [ModelResponse(parts=[TextPart(content=text)])])
    payload = await encode_model_message_payloads(payload, conversation_id=conversation_id)
    try:
        async with async_db_session.begin() as db:
            if pending_only:
                await ai_buddy_message_dao.update_pending(
                    db,
                    assistant_message_id,
                    {'model_messages': payload},
                )
            else:
                await ai_buddy_message_dao.update_pending(
                    db,
                    assistant_message_id,
                    {'status': status, 'model_messages': payload},
                )
            await ai_buddy_conversation_service.refresh_last_message(db=db, conversation_id=conversation_id)
    except Exception as exc:
        if pending_only:
            log.warning(f'回写编码步骤消息失败: {exc}')
            return
        raise
