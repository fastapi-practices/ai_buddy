from copy import deepcopy
from dataclasses import replace
from typing import Any

import anyio

from ag_ui.core import UserMessage
from pydantic_ai import AgentRunResult, ModelRequest, ModelResponse, UserPromptPart
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.common.exception import errors
from backend.common.log import log
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.work.inputs import build_run_context
from backend.plugin.ai_buddy.agent.work.persistence import (
    extract_assistant_messages,
    extract_assistant_run_messages,
    persist_regeneration,
    persist_terminal_regeneration,
)
from backend.plugin.ai_buddy.agent.work.runs import abort_prepared_run, activate_run
from backend.plugin.ai_buddy.agent.work.session_factory import open_chat_session
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.crud.crud_message_error import ai_buddy_message_error_dao
from backend.plugin.ai_buddy.dataclasses import RegenerationPersistenceContext
from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyMessageStatus, AIBuddyOrigin
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam, AIBuddyChatRegenerateParam
from backend.plugin.ai_buddy.schema.conversation import UpdateAIBuddyConversationParam
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.utils.message_converter import (
    expand_message_rows,
    filter_history_model_messages,
    get_message_row_index,
    get_message_row_model_message_payloads,
    get_regenerate_target,
    get_row_model_messages,
    is_user_message_row,
)
from backend.plugin.ai_buddy.utils.plan_store import delete_conversation_plan
from backend.plugin.ai_buddy.utils.turn_context import build_turn_context


class AIBuddyMessageService:
    """AI 消息服务类"""

    async def regenerate_from_user_message(  # ruff: ignore[complex-structure]
        self,
        *,
        user_id: int,
        conversation_id: str,
        pk: int,
        obj: AIBuddyChatRegenerateParam,
        accept: str | None,
    ) -> StreamingResponse:
        """
        根据最后一条用户消息重发 AI 回复

        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param pk: 消息主键
        :param obj: 请求体
        :param accept: Accept 请求头
        :return:
        """
        self._require_work_regeneration(agent_mode=obj.forwarded_props.agent_mode)
        run_context = build_run_context(
            run_input=obj,
            forwarded_props=obj.forwarded_props,
            default_conversation_id=conversation_id,
            expected_conversation_id=conversation_id,
        )
        forwarded_props = run_context.forwarded_props
        assert isinstance(forwarded_props, AIBuddyChatForwardedPropsParam)
        session = None
        try:
            async with async_db_session() as db:
                if forwarded_props.quote is not None and forwarded_props.quote.conversation_id is not None:
                    await ai_buddy_conversation_service.get_owned_conversation(
                        db=db, conversation_id=forwarded_props.quote.conversation_id, user_id=user_id
                    )
                state = await ai_buddy_conversation_service.get_chat_state(
                    db=db,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    must_exist=True,
                    require_messages=True,
                )
                assert state.conversation is not None
                target_index, _ = get_regenerate_target(state=state, pk=pk)
                forwarded_props = ai_buddy_conversation_service.resolve_work_location(
                    forwarded_props=forwarded_props, message_rows=state.message_rows
                )
                run_context = replace(
                    run_context,
                    forwarded_props=forwarded_props,
                    run_input=run_context.run_input.model_copy(
                        update={'forwarded_props': forwarded_props.model_dump(mode='json')}
                    ),
                )
                ai_buddy_conversation_service.validate_agent_mode(
                    conversation=state.conversation, forwarded_props=forwarded_props
                )
                self._require_work_regeneration(
                    agent_mode=forwarded_props.agent_mode,
                    turn_context=state.message_rows[target_index].turn_context,
                )
                session, agent = await open_chat_session(
                    db=db,
                    forwarded_props=forwarded_props,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )

            async with async_db_session.begin() as db:
                conversation = await ai_buddy_conversation_service.get_owned_conversation(
                    db=db,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    for_update=True,
                )
                if conversation is None:
                    raise errors.NotFoundError(msg='对话不存在')
                ai_buddy_conversation_service.validate_agent_mode(
                    conversation=conversation, forwarded_props=forwarded_props
                )
                self._require_work_regeneration(
                    agent_mode=forwarded_props.agent_mode,
                    archived=conversation.archived_time is not None,
                )
                await ai_buddy_conversation_service.ensure_idle(db=db, conversation_id=conversation_id)
                state = await ai_buddy_conversation_service.get_chat_state(
                    db=db,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    must_exist=True,
                    require_messages=True,
                )
                target_index, target_end_index = get_regenerate_target(state=state, pk=pk)
                forwarded_props = ai_buddy_conversation_service.resolve_work_location(
                    forwarded_props=forwarded_props, message_rows=state.message_rows
                )
                replacement = next(
                    (message for message in reversed(obj.messages) if isinstance(message, UserMessage)), None
                )
                content = replacement.content if replacement is not None else None
                if content is not None and not isinstance(content, str):
                    raise errors.RequestError(msg='重生成的替换消息必须是文本')
                if content is not None:
                    target_messages = get_row_model_messages(
                        model_messages=state.model_messages,
                        row_message_ranges=state.row_model_message_ranges,
                        row_index=target_index,
                    )
                    target_message = target_messages[0] if target_messages else None
                    if len(target_messages) != 1 or not isinstance(target_message, ModelRequest):
                        raise errors.RequestError(msg='仅支持编辑用户消息')
                    if not target_message.parts or not isinstance(target_message.parts[0], UserPromptPart):
                        raise errors.RequestError(msg='仅支持编辑用户消息')
                    if not isinstance(target_message.parts[0].content, str):
                        raise errors.RequestError(msg='当前消息暂不支持直接编辑')
                    if not content.strip():
                        raise errors.RequestError(msg='消息内容不能为空')

                    model_messages_payload = deepcopy(
                        get_message_row_model_message_payloads(state.message_rows[target_index])
                    )
                    model_payload = deepcopy(model_messages_payload[0])
                    model_payload['parts'][0]['content'] = content
                    model_messages_payload[0] = model_payload
                    await ai_buddy_message_dao.update(
                        db, state.message_rows[target_index].id, {'model_messages': model_messages_payload}
                    )
                    state.model_messages[target_end_index - 1] = replace(
                        target_message,
                        parts=[replace(target_message.parts[0], content=content), *target_message.parts[1:]],
                    )

                reply_start_index = target_index + 1
                replace_start_index = replace_end_index = insert_before_index = None
                if reply_start_index < len(state.message_rows):
                    next_user_index = next(
                        (
                            index
                            for index in range(reply_start_index, len(state.message_rows))
                            if is_user_message_row(
                                model_messages=state.model_messages,
                                row_index=index,
                                row_model_message_ranges=state.row_model_message_ranges,
                            )
                        ),
                        len(state.message_rows),
                    )
                    replace_start_index, replace_end_index, insert_before_index = (
                        (None, None, state.message_rows[reply_start_index].message_index)
                        if next_user_index == reply_start_index
                        else (
                            state.message_rows[reply_start_index].message_index,
                            state.message_rows[next_user_index - 1].message_index,
                            None,
                        )
                    )

                message_index = await ai_buddy_message_dao.get_next_message_index(db, conversation_id)
                assistant_placeholder = await ai_buddy_message_dao.create(
                    db,
                    {
                        'conversation_id': conversation_id,
                        'provider_id': forwarded_props.provider_id,
                        'model_id': forwarded_props.model_id,
                        'message_index': message_index,
                        'role': 'assistant',
                        'status': AIBuddyMessageStatus.pending,
                        'origin': AIBuddyOrigin.web,
                        'turn_context': build_turn_context(
                            forwarded_props=forwarded_props,
                            origin=AIBuddyOrigin.web,
                        ),
                        'model_messages': [],
                    },
                )
                await ai_buddy_conversation_dao.update(
                    db,
                    conversation.id,
                    UpdateAIBuddyConversationParam(
                        conversation_id=conversation.conversation_id,
                        title=conversation.title,
                        provider_id=forwarded_props.provider_id,
                        model_id=forwarded_props.model_id,
                        agent_mode=forwarded_props.agent_mode,
                        user_id=conversation.user_id,
                        project_id=conversation.project_id,
                        assistant_id=conversation.assistant_id,
                        goal=conversation.goal,
                        last_message_preview=conversation.last_message_preview,
                        last_message_time=conversation.last_message_time,
                        pinned_time=conversation.pinned_time,
                        archived_time=conversation.archived_time,
                    ),
                )
                persistence = RegenerationPersistenceContext(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    forwarded_props=forwarded_props,
                    assistant_message_id=assistant_placeholder.id,
                    insert_before_index=insert_before_index,
                    replace_start_index=replace_start_index,
                    replace_end_index=replace_end_index,
                )
                message_history = filter_history_model_messages(state.model_messages[:target_end_index])

                async def on_complete(result: AgentRunResult[Any]) -> None:
                    """
                    生成完成后持久化重发回复

                    :param result: Agent 运行结果
                    :return:
                    """
                    async with async_db_session.begin() as callback_db:
                        await persist_regeneration(
                            db=callback_db,
                            persistence=persistence,
                            messages=extract_assistant_run_messages(result),
                        )

                async def on_run_error(
                    message: str,
                    messages: list[ModelRequest | ModelResponse],
                    detail: dict[str, Any] | None = None,
                ) -> None:
                    """
                    持久化失败回复和错误详情

                    :param message: 错误原因
                    :param messages: 已生成的模型消息
                    :param detail: 错误详情
                    :return:
                    """
                    await persist_terminal_regeneration(
                        persistence=persistence,
                        messages=extract_assistant_messages(messages),
                        status=AIBuddyMessageStatus.error,
                        reason=message,
                        detail=detail,
                    )

                async def on_interrupted(messages: list[ModelRequest | ModelResponse]) -> None:
                    """
                    持久化中断前已生成的回复

                    :param messages: 已生成的模型消息
                    :return:
                    """
                    await persist_terminal_regeneration(
                        persistence=persistence,
                        messages=extract_assistant_messages(messages),
                        status=AIBuddyMessageStatus.interrupted,
                    )

                response = await session.stream(
                    user_id=user_id,
                    agent=agent,
                    run_context=run_context,
                    accept=accept,
                    message_history=message_history,
                    persistence=persistence,
                    on_complete=on_complete,
                    on_run_error=on_run_error,
                    on_interrupted=on_interrupted,
                )
            activate_run(conversation_id)
        except BaseException:
            # 屏蔽取消：任务取消时仍完成客户端关闭，避免连接泄漏
            with anyio.CancelScope(shield=True):
                try:
                    await abort_prepared_run(conversation_id)
                except Exception as abort_exc:
                    log.warning(f'释放聊天任务租约失败: {abort_exc}')
                if session is not None:
                    try:
                        await session.aclose()
                    except Exception as exc:
                        log.warning(f'关闭模型供应商客户端失败: {exc}')
            raise
        return response

    @staticmethod
    async def clear(
        *,
        db: AsyncSession,
        user_id: int,
        conversation_id: str,
    ) -> int:
        """
        清空对话消息

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :return:
        """
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        await ai_buddy_conversation_service.ensure_idle(db=db, conversation_id=conversation_id)

        await ai_buddy_message_error_dao.delete_by_conversation_id(db, conversation_id)
        count = await ai_buddy_message_dao.delete(db, conversation_id)
        await delete_conversation_plan(user_id=user_id, conversation_id=conversation_id)
        await ai_buddy_conversation_service.refresh_last_message(db=db, conversation_id=conversation_id)
        return count

    @staticmethod
    async def delete(
        *,
        db: AsyncSession,
        user_id: int,
        conversation_id: str,
        pk: int,
    ) -> int:
        """
        删除指定消息

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param pk: 消息主键
        :return:
        """
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        await ai_buddy_conversation_service.ensure_idle(db=db, conversation_id=conversation_id)
        message_rows = list(await ai_buddy_message_dao.get_all_by_message_index(db, conversation_id))
        target_message_index = get_message_row_index(message_rows=message_rows, pk=pk)
        model_messages, row_model_message_ranges = await expand_message_rows(message_rows)
        if not is_user_message_row(
            model_messages=model_messages,
            row_index=target_message_index,
            row_model_message_ranges=row_model_message_ranges,
        ):
            target_row_messages = get_row_model_messages(
                model_messages=model_messages,
                row_message_ranges=row_model_message_ranges,
                row_index=target_message_index,
            )
            if not any(isinstance(message, ModelResponse) for message in target_row_messages):
                raise errors.RequestError(msg='仅支持删除用户消息或 AI 回复')

        await ai_buddy_message_error_dao.delete_by_message_ids(db, [pk])
        count = await ai_buddy_message_dao.delete_message(db, pk)
        await ai_buddy_conversation_service.refresh_last_message(db=db, conversation_id=conversation_id)
        return count

    @staticmethod
    def _require_work_regeneration(
        *, agent_mode: AIBuddyAgentMode, turn_context: dict[str, Any] | None = None, archived: bool = False
    ) -> None:
        """
        归档对话不能重生成，编码重生成必须由桌面重新提交执行连接

        :param agent_mode: 代理模式
        :param turn_context: 消息轮次上下文
        :param archived: 是否已归档
        :return:
        """
        if archived:
            raise errors.ConflictError(msg='对话已归档，请恢复后再生成')
        if agent_mode == AIBuddyAgentMode.coding or (turn_context or {}).get('agent_mode') == AIBuddyAgentMode.coding:
            raise errors.RequestError(msg='编码回复暂不支持重生成，请在桌面重新连接工作区或 ACP Agent 后重新发送')


ai_buddy_message_service: AIBuddyMessageService = AIBuddyMessageService()
