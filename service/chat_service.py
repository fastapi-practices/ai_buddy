from dataclasses import replace

import anyio

from ag_ui.core import RunAgentInput, ToolMessage, UserMessage
from pydantic_ai.messages import sanitize_messages
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.common.exception import errors
from backend.common.log import log
from backend.database.db import async_db_session, uuid4_str
from backend.plugin.ai_buddy.agent.coding.conversation_run import run_conversation_coding
from backend.plugin.ai_buddy.agent.coding.session import resolve_coding_invocation
from backend.plugin.ai_buddy.agent.work.inputs import build_run_context, decode_input_messages, sanitize_input_messages
from backend.plugin.ai_buddy.agent.work.runs import abort_prepared_run, activate_run
from backend.plugin.ai_buddy.agent.work.session_factory import open_chat_session
from backend.plugin.ai_buddy.crud.crud_follow_up import ai_buddy_follow_up_dao
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.dataclasses import CompletionPersistenceContext
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyMessageRole,
    AIBuddyMessageStatus,
    AIBuddyOrigin,
)
from backend.plugin.ai_buddy.schema.chat import (
    AIBuddyChatCompletionParam,
    AIBuddyChatForwardedPropsParam,
    AIBuddyForwardedPropsParam,
)
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.service.workspace_service import ai_buddy_workspace_service
from backend.plugin.ai_buddy.utils.media_store import dump_model_message_payloads, encode_model_message_payloads
from backend.plugin.ai_buddy.utils.message_converter import (
    build_chat_message_record,
    filter_history_model_messages,
    parse_current_turn_input,
)
from backend.plugin.ai_buddy.utils.turn_context import build_turn_context
from backend.plugin.ai_buddy.utils.workspace import validate_workspace_id


class AIBuddyChatService:
    """AI 聊天服务类"""

    async def run_completion(  # ruff: ignore[complex-structure]
        self,
        *,
        user_id: int,
        run_input: RunAgentInput,
        assistant_id: int | None,
        forwarded_props: AIBuddyForwardedPropsParam,
        accept: str | None,
        empty_message_error: str,
        origin: AIBuddyOrigin = AIBuddyOrigin.web,
        followup_id: int | None = None,
    ) -> StreamingResponse:
        """
        运行一轮流式生成

        :param user_id: 用户 ID
        :param run_input: AG-UI 运行请求
        :param assistant_id: 新建对话时的助手 ID
        :param forwarded_props: 扩展参数
        :param accept: Accept 请求头
        :param empty_message_error: 空消息错误文案
        :param origin: 消息来源
        :param followup_id: 持久跟进 ID，派发结果与本轮消息原子提交
        :return:
        """
        run_context = build_run_context(run_input=run_input, forwarded_props=forwarded_props)
        conversation_id = run_context.conversation_id
        forwarded_props = run_context.forwarded_props
        run_id = run_context.run_input.run_id
        continuing = bool(run_context.run_input.resume) or any(
            isinstance(message, ToolMessage) for message in run_context.run_input.messages
        )
        coding = (
            isinstance(forwarded_props, AIBuddyChatForwardedPropsParam)
            and forwarded_props.agent_mode == AIBuddyAgentMode.coding
        )
        if continuing and coding:
            raise errors.RequestError(msg='编码模式请使用编码审批接口继续运行')
        if continuing:
            current_messages, prompt, has_binary_input = [], '', False
        else:
            try:
                decoded_messages = decode_input_messages(messages=run_context.run_input.messages)
            except Exception as e:
                log.warning(f'聊天消息加载失败: {e}')
                raise errors.RequestError(msg='聊天消息格式非法') from e
            current_messages, prompt, has_binary_input = parse_current_turn_input(messages=decoded_messages)
        if coding:
            current_messages = sanitize_messages(current_messages, allow_uploaded_files=True)
            current_messages, prompt, has_binary_input = parse_current_turn_input(messages=current_messages)
        if not continuing and not prompt and not has_binary_input:
            raise errors.RequestError(msg=empty_message_error)
        if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam):
            async with async_db_session() as db:
                if forwarded_props.quote is not None and forwarded_props.quote.conversation_id is not None:
                    await ai_buddy_conversation_service.get_owned_conversation(
                        db=db, conversation_id=forwarded_props.quote.conversation_id, user_id=user_id
                    )
                forwarded_props = await self._resolve_conversation_binding(
                    db=db,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    forwarded_props=forwarded_props,
                )
            run_context = replace(
                run_context,
                forwarded_props=forwarded_props,
                run_input=run_context.run_input.model_copy(
                    update={'forwarded_props': forwarded_props.model_dump(mode='json')}
                ),
            )

        agent_session = None
        try:
            # 编码后台任务必须等外层事务提交后再启动，避免新对话在独立连接不可见
            if coding:
                assert isinstance(forwarded_props, AIBuddyChatForwardedPropsParam)
                async with async_db_session() as db:
                    conversation = await ai_buddy_conversation_service.get_owned_conversation(
                        db=db,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        must_exist=False,
                    )
                    await resolve_coding_invocation(
                        db=db,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        forwarded_props=forwarded_props,
                        permission_mode=forwarded_props.permission_mode,
                        project_id=conversation.project_id if conversation is not None else forwarded_props.project_id,
                    )
            else:
                async with async_db_session() as db:
                    agent_session, agent = await open_chat_session(
                        db=db,
                        forwarded_props=forwarded_props,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        assistant_id=assistant_id,
                        origin=origin,
                    )
                current_messages = sanitize_input_messages(
                    agent=agent,
                    run_input=run_context.run_input,
                    messages=current_messages,
                )
                if not continuing:
                    current_messages, prompt, has_binary_input = parse_current_turn_input(messages=current_messages)
                    if not prompt and not has_binary_input:
                        raise errors.RequestError(msg=empty_message_error)
            payload_messages = await dump_model_message_payloads(current_messages)
            payload_messages = await encode_model_message_payloads(payload_messages, conversation_id=conversation_id)
            user_message_record = build_chat_message_record(
                role=AIBuddyMessageRole.user, model_messages=payload_messages
            )

            async with async_db_session.begin() as session:
                if continuing:
                    await ai_buddy_conversation_service.get_owned_conversation(
                        db=session,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        for_update=True,
                    )
                await ai_buddy_conversation_service.prepare_completion(
                    db=session,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    forwarded_props=forwarded_props,
                    prompt=prompt,
                    assistant_id=assistant_id,
                    origin=origin,
                )
                turn_context = build_turn_context(forwarded_props=forwarded_props, origin=origin)
                if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam):
                    forwarded_props = await self._resolve_conversation_binding(
                        db=session,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        forwarded_props=forwarded_props,
                    )
                    run_context = replace(
                        run_context,
                        forwarded_props=forwarded_props,
                        run_input=run_context.run_input.model_copy(
                            update={'forwarded_props': forwarded_props.model_dump(mode='json')}
                        ),
                    )
                    turn_context = build_turn_context(forwarded_props=forwarded_props, origin=origin)
                followup = None
                if followup_id is not None:
                    followup = await ai_buddy_follow_up_dao.get(session, followup_id)
                    if (
                        followup is None
                        or followup.deleted
                        or followup.user_id != user_id
                        or followup.conversation_id != conversation_id
                        or followup.run_id != run_id
                        or followup.status != 'dispatched'
                        or followup.dispatch_committed
                    ):
                        raise errors.ConflictError(msg='跟进派发认领已失效')
                next_message_index = await ai_buddy_message_dao.get_next_message_index(session, conversation_id)
                pending_branch = await ai_buddy_message_dao.consume_pending_branch(session, conversation_id)
                if pending_branch is not None:
                    turn_context['branch'] = pending_branch
                if not continuing:
                    client_message_id = next(
                        (message.id for message in reversed(run_context.run_input.messages) if message.role == 'user'),
                        None,
                    )
                    submitted = (
                        await ai_buddy_message_dao.get_by_client_message_id(session, conversation_id, client_message_id)
                        if client_message_id
                        else None
                    )
                    if submitted is not None and submitted.model_messages == user_message_record['model_messages']:
                        raise errors.ConflictError(msg='消息已提交，请同步对话后查看结果')
                    await ai_buddy_message_dao.create(
                        session,
                        {
                            'conversation_id': conversation_id,
                            'provider_id': forwarded_props.provider_id,
                            'model_id': forwarded_props.model_id,
                            'message_index': next_message_index,
                            'status': AIBuddyMessageStatus.success,
                            'origin': origin,
                            'client_message_id': client_message_id,
                            'turn_context': turn_context,
                            **user_message_record,
                        },
                    )
                assistant_message = await ai_buddy_message_dao.create(
                    session,
                    {
                        'conversation_id': conversation_id,
                        'provider_id': forwarded_props.provider_id,
                        'model_id': forwarded_props.model_id,
                        'message_index': next_message_index if continuing else next_message_index + 1,
                        'role': AIBuddyMessageRole.assistant,
                        'status': AIBuddyMessageStatus.pending,
                        'origin': origin,
                        'turn_context': turn_context,
                        'model_messages': [],
                    },
                )
                assistant_message_id = assistant_message.id
                if followup is not None:
                    followup.message_id = assistant_message_id
                    followup.dispatch_committed = True
                await ai_buddy_conversation_service.refresh_last_message(db=session, conversation_id=conversation_id)
                state = await ai_buddy_conversation_service.get_chat_state(
                    db=session,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    must_exist=True,
                    require_messages=True,
                )
                message_history = filter_history_model_messages(state.model_messages)
                persistence = CompletionPersistenceContext(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    forwarded_props=forwarded_props,
                    title=state.conversation.title if state.conversation else prompt,
                    assistant_message_id=assistant_message_id,
                )
                if not coding:
                    assert agent_session is not None
                    response = await agent_session.stream(
                        user_id=user_id,
                        agent=agent,
                        run_context=run_context,
                        accept=accept,
                        message_history=message_history,
                        persistence=persistence,
                    )
            if coding:
                assert isinstance(forwarded_props, AIBuddyChatForwardedPropsParam)
                response = await run_conversation_coding(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    prompt=prompt,
                    forwarded_props=forwarded_props,
                    assistant_message_id=assistant_message_id,
                    run_id=run_id,
                )
            activate_run(conversation_id)
        except BaseException as exc:
            # 屏蔽取消：任务取消时仍完成客户端关闭，避免连接泄漏
            with anyio.CancelScope(shield=True):
                try:
                    await abort_prepared_run(conversation_id)
                except Exception as abort_exc:
                    log.warning(f'释放聊天任务租约失败: {abort_exc}')
                if agent_session is not None:
                    try:
                        await agent_session.aclose()
                    except Exception as close_exc:
                        log.warning(f'关闭模型供应商客户端失败: {close_exc}')
            if isinstance(exc, IntegrityError):
                raise errors.ConflictError(msg='当前对话已发生变化，请重试') from exc
            raise
        assert response is not None
        return response

    async def run_text_prompt(
        self,
        *,
        user_id: int,
        conversation_id: str,
        prompt: str,
        forwarded_props: AIBuddyForwardedPropsParam,
        origin: AIBuddyOrigin,
        assistant_id: int | None = None,
        accept: str | None = None,
    ) -> StreamingResponse:
        """
        用纯文本开工一轮，供 IM 通道和定时任务使用

        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param prompt: 用户文本
        :param forwarded_props: 扩展参数
        :param origin: 来源
        :param assistant_id: 助手 ID
        :param accept: Accept 请求头
        :return:
        """
        run_input = RunAgentInput(
            thread_id=conversation_id,
            run_id=uuid4_str(),
            messages=[UserMessage(id=uuid4_str(), content=prompt)],
            tools=[],
            context=[],
            forwarded_props=forwarded_props.model_dump(mode='json', by_alias=True),
        )
        return await self.run_completion(
            user_id=user_id,
            run_input=run_input,
            assistant_id=assistant_id,
            forwarded_props=forwarded_props,
            accept=accept,
            empty_message_error='提示词不能为空',
            origin=origin,
        )

    async def create_completion(
        self,
        *,
        user_id: int,
        obj: AIBuddyChatCompletionParam,
        accept: str | None,
    ) -> StreamingResponse:
        """
        创建流式对话

        :param user_id: 用户 ID
        :param obj: 请求体
        :param accept: Accept 请求头
        :return:
        """
        return await self.run_completion(
            user_id=user_id,
            run_input=obj,
            assistant_id=obj.forwarded_props.assistant_id,
            forwarded_props=obj.forwarded_props,
            accept=accept,
            empty_message_error='当前轮用户消息不能为空',
        )

    @staticmethod
    async def _resolve_conversation_binding(
        *, db: AsyncSession, user_id: int, conversation_id: str, forwarded_props: AIBuddyChatForwardedPropsParam
    ) -> AIBuddyChatForwardedPropsParam:
        """
        校验会话模式、固定工作位置并解析编码工作区绑定

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param forwarded_props: 本轮扩展参数
        :return:
        """
        conversation = await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            must_exist=False,
        )
        if conversation is not None:
            ai_buddy_conversation_service.validate_agent_mode(
                conversation=conversation, forwarded_props=forwarded_props
            )
        message_rows = (
            await ai_buddy_message_dao.get_all_by_message_index(db, conversation_id)
            if conversation is not None or forwarded_props.agent_mode == AIBuddyAgentMode.coding
            else []
        )
        forwarded_props = ai_buddy_conversation_service.resolve_work_location(
            forwarded_props=forwarded_props, message_rows=message_rows
        )
        if forwarded_props.agent_mode != AIBuddyAgentMode.coding:
            return forwarded_props
        inherited_workspace_id = None
        for row in reversed(message_rows):
            context = row.turn_context
            if not isinstance(context, dict) or context.get('workspace_id') is None:
                continue
            inherited_workspace_id = validate_workspace_id(context['workspace_id'])
            break
        requested_workspace_id = forwarded_props.workspace_id
        if (
            inherited_workspace_id is not None
            and requested_workspace_id is not None
            and inherited_workspace_id != requested_workspace_id
        ):
            raise errors.ConflictError(msg='同一对话已绑定其他工作区')
        workspace_id = requested_workspace_id or inherited_workspace_id
        if workspace_id is None:
            return forwarded_props
        await ai_buddy_workspace_service.get(db=db, user_id=user_id, workspace_id=workspace_id)
        if workspace_id == requested_workspace_id:
            return forwarded_props
        return forwarded_props.model_copy(update={'workspace_id': workspace_id})


ai_buddy_chat_service: AIBuddyChatService = AIBuddyChatService()
