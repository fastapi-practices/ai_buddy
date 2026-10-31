import asyncio

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.common.exception import errors
from backend.common.log import log
from backend.common.pagination import cursor_paging_data
from backend.database.db import async_db_session, uuid4_str
from backend.plugin.ai_buddy.agent.coding.approvals import resolve_approval
from backend.plugin.ai_buddy.agent.coding.sandbox_providers import destroy_conversation_sandbox
from backend.plugin.ai_buddy.agent.work.runs import (
    attach_event_stream,
    has_active_run,
    request_stop_run,
    wait_run_stopped,
)
from backend.plugin.ai_buddy.crud.crud_assistant import ai_buddy_assistant_dao
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.crud.crud_message_error import ai_buddy_message_error_dao
from backend.plugin.ai_buddy.crud.crud_project import ai_buddy_project_dao
from backend.plugin.ai_buddy.dataclasses import ChatConversationState
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyConversationAuditAction,
    AIBuddyConversationSurface,
    AIBuddyConversationView,
    AIBuddyExecutionBackend,
    AIBuddyMessageStatus,
    AIBuddyOrigin,
)
from backend.plugin.ai_buddy.model.conversation import AIBuddyConversation
from backend.plugin.ai_buddy.model.message import AIBuddyMessage
from backend.plugin.ai_buddy.schema.chat import (
    AIBuddyChatForwardedPropsParam,
    AIBuddyForwardedPropsParam,
    conversation_surface_of,
)
from backend.plugin.ai_buddy.schema.conversation import (
    CreateAIBuddyConversationParam,
    GetAIBuddyConversationDetail,
    UpdateAIBuddyConversationArchiveParam,
    UpdateAIBuddyConversationParam,
    UpdateAIBuddyConversationPinnedParam,
    UpdateAIBuddyConversationSourceParam,
    UpdateAIBuddyConversationTitleParam,
    UpdateAIBuddyConversationWorkspaceParam,
)
from backend.plugin.ai_buddy.service.assistant_service import ai_buddy_assistant_service
from backend.plugin.ai_buddy.service.conversation_audit_service import ai_buddy_conversation_audit_service
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service
from backend.plugin.ai_buddy.service.step_service import ai_buddy_step_service
from backend.plugin.ai_buddy.utils.conversation_title import (
    normalize_conversation_title,
    normalize_generated_conversation_title,
)
from backend.plugin.ai_buddy.utils.history_cursor import encode_history_cursor
from backend.plugin.ai_buddy.utils.media_store import track_copied_attachments
from backend.plugin.ai_buddy.utils.message_converter import (
    expand_message_row_metadata,
    expand_message_rows,
    extract_payload_preview_text,
    get_message_row_model_message_payloads,
    normalize_message_preview,
)
from backend.plugin.ai_buddy.utils.message_snapshot import serialize_messages_to_snapshot
from backend.plugin.ai_buddy.utils.plan_store import copy_conversation_plan, delete_conversation_plan
from backend.utils.timezone import timezone


class AIBuddyConversationService:
    """AI 对话服务类"""

    @staticmethod
    def validate_agent_mode(*, conversation: AIBuddyConversation, forwarded_props: AIBuddyForwardedPropsParam) -> None:
        """
        允许对话与工作模式互切，编码会话保持独立

        :param conversation: 当前对话
        :param forwarded_props: 本轮扩展参数
        :return:
        """
        if (
            isinstance(forwarded_props, AIBuddyChatForwardedPropsParam)
            and conversation.agent_mode is not None
            and conversation.agent_mode != forwarded_props.agent_mode
            and AIBuddyAgentMode.coding in (conversation.agent_mode, forwarded_props.agent_mode)
        ):
            raise errors.ConflictError(msg='编码模式与对话、工作模式不能互切，请新建对话')

    @staticmethod
    def resolve_work_location(
        *, forwarded_props: AIBuddyChatForwardedPropsParam, message_rows: Sequence[AIBuddyMessage]
    ) -> AIBuddyChatForwardedPropsParam:
        """
        继承首轮工作位置并拒绝已开始会话的位置变更

        :param forwarded_props: 本轮扩展参数
        :param message_rows: 按消息顺序排列的历史记录
        :return:
        """
        if not message_rows:
            return forwarded_props
        backend = next(
            (
                row.turn_context['execution_backend']
                for row in message_rows
                if isinstance(row.turn_context, dict) and row.turn_context.get('execution_backend') is not None
            ),
            None,
        )
        if backend is None:
            return forwarded_props
        backend = AIBuddyExecutionBackend(backend)
        if 'execution_backend' in forwarded_props.model_fields_set and forwarded_props.execution_backend != backend:
            raise errors.ConflictError(msg='对话开始后不能更改工作位置，请新建对话')
        if forwarded_props.execution_backend == backend:
            return forwarded_props
        return forwarded_props.model_copy(update={'execution_backend': backend})

    async def prepare_completion(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        forwarded_props: AIBuddyForwardedPropsParam,
        prompt: str,
        assistant_id: int | None,
        origin: AIBuddyOrigin = AIBuddyOrigin.web,
        channel_id: int | None = None,
    ) -> None:
        """
        创建或更新本次生成对应的对话

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param forwarded_props: 聊天扩展参数
        :param prompt: 当前轮用户输入
        :param assistant_id: 新建对话时的助手 ID
        :param origin: 消息来源
        :param channel_id: 消息通道 ID
        :return:
        """
        conversation = await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            must_exist=False,
            for_update=True,
        )
        surface = conversation_surface_of(forwarded_props)
        if conversation:
            self.validate_agent_mode(conversation=conversation, forwarded_props=forwarded_props)
            if conversation.archived_time is not None:
                raise errors.ConflictError(msg='对话已归档，请恢复后再生成')
            if conversation.surface != surface:
                if surface == AIBuddyConversationSurface.image:
                    raise errors.RequestError(msg='独立生图不能写入聊天对话')
                raise errors.RequestError(msg='生图会话不能用于聊天')
            await self.ensure_idle(db=db, conversation_id=conversation_id)
            await ai_buddy_conversation_dao.update(
                db,
                conversation.id,
                UpdateAIBuddyConversationParam(
                    conversation_id=conversation.conversation_id,
                    title=conversation.title,
                    provider_id=forwarded_props.provider_id,
                    model_id=forwarded_props.model_id,
                    agent_mode=(
                        forwarded_props.agent_mode
                        if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam)
                        else None
                    ),
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
            return
        resolved_assistant_id = None
        resolved_project_id = getattr(forwarded_props, 'project_id', None)
        if resolved_project_id is not None:
            project = await ai_buddy_project_dao.get(db, resolved_project_id)
            if project is None or project.user_id != user_id:
                raise errors.NotFoundError(msg='项目不存在')
        if assistant_id is not None:
            assistant = await ai_buddy_assistant_service.get(db=db, pk=assistant_id, user_id=user_id)
            resolved_assistant_id = assistant.id
        await ai_buddy_conversation_dao.create(
            db,
            CreateAIBuddyConversationParam(
                conversation_id=conversation_id,
                title=normalize_generated_conversation_title(title=prompt),
                provider_id=forwarded_props.provider_id,
                model_id=forwarded_props.model_id,
                agent_mode=(
                    forwarded_props.agent_mode if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam) else None
                ),
                user_id=user_id,
                assistant_id=resolved_assistant_id,
                project_id=resolved_project_id,
                origin=origin,
                surface=surface,
                channel_id=channel_id,
            ),
        )
        await ai_buddy_assistant_service.record_usage(db=db, pk=resolved_assistant_id)

    @staticmethod
    async def get_workspace_context(
        *,
        db: AsyncSession,
        user_id: int | None,
        conversation_id: str | None,
        assistant_id: int | None,
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """
        加载会话工作区与助手指令

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param assistant_id: 新建对话时的助手 ID
        :return:
        """
        conversation_goal = None
        project_name = None
        assistant_name = None
        assistant_prompt = None
        conversation_exists = False
        bound_assistant_id = assistant_id
        if conversation_id is not None and user_id is not None:
            conversation = await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
            if conversation is not None and conversation.user_id == user_id:
                conversation_exists = True
                conversation_goal = conversation.goal
                bound_assistant_id = conversation.assistant_id
                if conversation.project_id is not None:
                    project = await ai_buddy_project_dao.get(db, conversation.project_id)
                    if project is not None and project.user_id == user_id:
                        project_name = project.name
        if bound_assistant_id is not None and user_id is not None:
            assistant = await ai_buddy_assistant_dao.get_by_id_and_user_id(db, bound_assistant_id, user_id)
            if assistant is not None:
                assistant_name = assistant.name
                assistant_prompt = assistant.prompt
            elif not conversation_exists:
                raise errors.NotFoundError(msg='助手不存在')
        return conversation_goal, project_name, assistant_name, assistant_prompt

    @staticmethod
    async def ensure_idle(*, db: AsyncSession, conversation_id: str) -> None:
        """
        确认对话可以开始新的生成

        进行中的后台任务会拒绝新请求，无后台任务的残留 pending 会被标为中断

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        if await has_active_run(conversation_id):
            raise errors.ConflictError(msg='当前对话正在生成，请稍后再试')
        pending_rows = await ai_buddy_message_dao.get_pending(db, conversation_id)
        for row in pending_rows:
            await ai_buddy_message_dao.update_pending(
                db,
                row.id,
                {'status': AIBuddyMessageStatus.interrupted},
            )

    @staticmethod
    async def reconcile_stale_pending(*, stale_after_seconds: int = 60) -> int:
        """
        将租约已失效的残留 pending 消息收敛为中断

        :param stale_after_seconds: 最短静默秒数
        :return:
        """
        stale_before = timezone.now() - timedelta(seconds=stale_after_seconds)
        async with async_db_session.begin() as db:
            stale_rows = await ai_buddy_message_dao.get_stale_pending(db, stale_before)
            rows_by_conversation: dict[str, list[int]] = {}
            for row in stale_rows:
                rows_by_conversation.setdefault(row.conversation_id, []).append(row.id)

        reconciled = 0
        for conversation_id, message_ids in rows_by_conversation.items():
            try:
                if await has_active_run(conversation_id):
                    continue
                async with async_db_session.begin() as db:
                    for message_id in message_ids:
                        reconciled += await ai_buddy_message_dao.update_pending(
                            db,
                            message_id,
                            {'status': AIBuddyMessageStatus.interrupted},
                        )
            except Exception as exc:
                log.warning(f'收敛残留聊天消息失败 conversation_id={conversation_id}: {exc}')
        return reconciled

    async def stop_generation(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
    ) -> None:
        """
        停止对话当前生成

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :return:
        """
        await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        # 等待后台任务保存中断结果时不能持有对话行锁
        if await request_stop_run(conversation_id):
            if not await wait_run_stopped(conversation_id):
                raise errors.ServerError(msg='停止对话生成超时，请稍后重试')
            return
        await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        await self.ensure_idle(db=db, conversation_id=conversation_id)

    async def subscribe_events(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        after_id: str | None = None,
    ) -> StreamingResponse:
        """
        重放并订阅对话当前生成流

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param after_id: 客户端已收到的最后一个事件 ID
        :return:
        """
        await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            must_exist=True,
        )
        return await attach_event_stream(conversation_id=conversation_id, after_id=after_id or '0-0')

    async def resolve_coding_approval(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        request_id: str,
        approved: bool,
    ) -> None:
        """
        校验对话归属后提交当前编码运行的审批

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param request_id: 输入请求 ID
        :param approved: 是否批准
        :return:
        """
        await self.get_owned_conversation(db=db, conversation_id=conversation_id, user_id=user_id)
        await resolve_approval(
            conversation_id=conversation_id, user_id=user_id, request_id=request_id, approved=approved
        )

    @staticmethod
    async def get_owned_conversation(
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        must_exist: bool = True,
        for_update: bool = False,
    ) -> AIBuddyConversation | None:
        """
        获取当前用户所属对话

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param must_exist: 对话是否必须存在
        :param for_update: 是否锁定对话行
        :return:
        """
        conversation = (
            await ai_buddy_conversation_dao.get_by_conversation_id_for_update(db, conversation_id)
            if for_update
            else await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
        )
        if not conversation:
            if must_exist:
                raise errors.NotFoundError(msg='对话不存在')
            return None
        if conversation.user_id != user_id:
            raise errors.NotFoundError(msg='对话不存在')
        return conversation

    @staticmethod
    async def refresh_last_message(*, db: AsyncSession, conversation_id: str) -> None:
        """
        按当前消息重算对话最后一条预览

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        conversation = await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
        if conversation is None:
            return
        rows = list(await ai_buddy_message_dao.get_all_by_message_index(db, conversation_id))
        preview = None
        message_time = None
        for row in reversed(rows):
            if row.role == 'system' and (row.turn_context or {}).get('branch_pending'):
                continue
            payloads = get_message_row_model_message_payloads(row)
            if row.status == AIBuddyMessageStatus.pending and not payloads:
                continue
            preview = normalize_message_preview(text=extract_payload_preview_text(payloads))
            message_time = row.created_time
            break
        await ai_buddy_conversation_dao.update_last_message(
            db,
            conversation.id,
            preview=preview,
            message_time=message_time,
        )

    async def get_chat_state(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        must_exist: bool,
        require_messages: bool = False,
    ) -> ChatConversationState:
        """
        加载聊天上下文状态

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param must_exist: 对话是否必须存在
        :param require_messages: 是否要求对话消息存在
        :return:
        """
        conversation = await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            must_exist=must_exist,
        )
        if not conversation:
            return ChatConversationState(
                conversation=None,
                message_rows=[],
                model_messages=[],
                row_model_message_ranges=[],
            )
        message_rows = list(await ai_buddy_message_dao.get_all_by_message_index(db, conversation_id))
        if require_messages and not message_rows:
            raise errors.RequestError(msg='对话消息不存在')
        model_messages, row_model_message_ranges = await expand_message_rows(message_rows)
        return ChatConversationState(
            conversation=conversation,
            message_rows=message_rows,
            model_messages=model_messages,
            row_model_message_ranges=row_model_message_ranges,
        )

    async def get(
        self, *, db: AsyncSession, conversation_id: str, user_id: int, message_limit: int | None = None
    ) -> GetAIBuddyConversationDetail:
        """
        获取对话详情

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param message_limit: 最近消息数量上限
        :return:
        """
        conversation = await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )

        history_has_more = False
        history_cursor = None
        if message_limit is None:
            message_rows = await ai_buddy_message_dao.get_all_by_message_index(db, conversation.conversation_id)
        else:
            recent_rows = list(
                await ai_buddy_message_dao.get_history_page(
                    db, conversation.conversation_id, before=None, limit=message_limit + 1
                )
            )
            history_has_more = len(recent_rows) > message_limit
            message_rows = list(reversed(recent_rows[:message_limit]))
            if history_has_more and message_rows:
                history_cursor = encode_history_cursor(row=message_rows[0])
        model_messages, row_model_message_ranges = await expand_message_rows(message_rows)
        message_ids, provider_ids, model_ids, message_indexes, turn_contexts = expand_message_row_metadata(
            message_rows,
            row_model_message_ranges,
        )
        error_rows = await ai_buddy_message_error_dao.get_all_by_message_ids(
            db,
            [row.id for row in message_rows],
        )
        errors = {row.message_id: (row.message, row.detail) for row in error_rows}
        error_fallbacks = [
            {
                'message_id': row.id,
                'conversation_id': row.conversation_id,
                'provider_id': row.provider_id,
                'model_id': row.model_id,
                'message_index': row.message_index,
                'created_time': row.created_time,
            }
            for row, (start, end) in zip(message_rows, row_model_message_ranges, strict=False)
            if end == start and row.id in errors
        ]

        messages_snapshot = await asyncio.to_thread(
            serialize_messages_to_snapshot,
            model_messages,
            conversation_id=conversation.conversation_id,
            message_ids=message_ids,
            provider_ids=provider_ids,
            model_ids=model_ids,
            message_indexes=message_indexes,
            turn_contexts=turn_contexts,
            errors=errors,
            error_fallbacks=error_fallbacks,
        )
        return GetAIBuddyConversationDetail(
            id=conversation.id,
            conversation_id=conversation.conversation_id,
            title=conversation.title,
            project_id=conversation.project_id,
            assistant_id=conversation.assistant_id,
            goal=conversation.goal,
            origin=conversation.origin,
            surface=conversation.surface,
            source=conversation.source,
            agent_mode=conversation.agent_mode,
            is_pinned=conversation.pinned_time is not None,
            is_archived=conversation.archived_time is not None,
            provider_id=conversation.provider_id,
            model_id=conversation.model_id,
            revision=conversation.revision,
            created_time=conversation.created_time,
            updated_time=conversation.updated_time,
            is_generating=await has_active_run(conversation.conversation_id),
            messages_snapshot=messages_snapshot,
            history_has_more=history_has_more,
            history_cursor=history_cursor,
        )

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        user_id: int,
        project_id: int | None = None,
        assistant_id: int | None = None,
        q: str | None = None,
        archived: bool = False,
        surface: AIBuddyConversationSurface = AIBuddyConversationSurface.chat,
        view: AIBuddyConversationView | None = None,
        agent_mode: AIBuddyAgentMode | None = None,
    ) -> dict[str, Any]:
        """
        获取对话列表

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param project_id: 项目 ID
        :param assistant_id: 助手 ID
        :param q: 标题关键字
        :param archived: 是否归档
        :param surface: 会话入口
        :param view: 聊天列表视图
        :param agent_mode: 最近一轮模式
        :return:
        """
        conversation_select = await ai_buddy_conversation_dao.get_select(
            user_id,
            project_id=project_id,
            assistant_id=assistant_id,
            q=q,
            archived=archived,
            surface=surface,
            view=view,
            agent_mode=agent_mode,
        )
        page_data = await cursor_paging_data(db, conversation_select)
        page_data['items'] = [
            {
                'id': item['id'],
                'conversation_id': item['conversation_id'],
                'title': item['title'],
                'project_id': item.get('project_id'),
                'assistant_id': item.get('assistant_id'),
                'origin': item.get('origin'),
                'source': item.get('source', 'cloud'),
                'surface': item.get('surface'),
                'agent_mode': item.get('agent_mode'),
                'is_pinned': item['pinned_time'] is not None,
                'is_archived': item.get('archived_time') is not None,
                'is_generating': await has_active_run(item['conversation_id']),
                'last_message_preview': item.get('last_message_preview'),
                'last_message_time': item.get('last_message_time'),
                'revision': item.get('revision', 1),
                'created_time': item['created_time'],
                'updated_time': item['updated_time'],
            }
            for item in page_data['items']
        ]
        return page_data

    @staticmethod
    def check_revision(*, conversation: AIBuddyConversation, expected: int | None) -> None:
        """
        校验客户端读到的修订号并推进修订，其他设备已修改时返回冲突，不静默覆盖

        :param conversation: 已加锁的对话
        :param expected: 客户端读到的修订号，为空则不检查
        :return:
        """
        if expected is not None and expected != conversation.revision:
            raise errors.ConflictError(msg=f'对话已被其他设备修改，请同步后重试（当前修订号 {conversation.revision}）')
        conversation.revision += 1

    async def update(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        obj: UpdateAIBuddyConversationTitleParam,
    ) -> int:
        """
        更新对话标题

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param obj: 更新参数
        :return:
        """
        conversation = await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        self.check_revision(conversation=conversation, expected=obj.expected_revision)
        title = normalize_conversation_title(title=obj.title, fallback='')
        if not title:
            raise errors.RequestError(msg='对话标题不能为空')
        if len(title) > 256:
            raise errors.RequestError(msg='对话标题过长')
        return await ai_buddy_conversation_dao.update_title(db, conversation.id, title)

    async def update_pinned_status(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        obj: UpdateAIBuddyConversationPinnedParam,
    ) -> int:
        """
        更新对话置顶状态

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param obj: 更新参数
        :return:
        """
        conversation = await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        self.check_revision(conversation=conversation, expected=obj.expected_revision)
        return await ai_buddy_conversation_dao.update_pinned_time(
            db,
            conversation.id,
            timezone.now() if obj.is_pinned else None,
        )

    async def update_archive_status(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        obj: UpdateAIBuddyConversationArchiveParam,
    ) -> int:
        """
        更新对话归档状态，归档前停止当前生成

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param obj: 归档参数
        :return:
        """
        if obj.is_archived:
            await self.stop_generation(db=db, conversation_id=conversation_id, user_id=user_id)
        conversation = await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        self.check_revision(conversation=conversation, expected=obj.expected_revision)
        if obj.is_archived:
            # 加锁后再次检查，防止等待结束后有新生成抢先启动
            await self.ensure_idle(db=db, conversation_id=conversation_id)
        return await ai_buddy_conversation_dao.update_archived_time(
            db,
            conversation.id,
            timezone.now() if obj.is_archived else None,
        )

    async def update_source(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        obj: UpdateAIBuddyConversationSourceParam,
    ) -> int:
        """
        在云端与本机之间迁移会话事实源，会话行不变，ID、顺序、附件引用和删除状态都原样保留；
        迁移前停止当前生成，避免迁移期间两端同时写入

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param obj: 迁移参数
        :return:
        """
        await self.stop_generation(db=db, conversation_id=conversation_id, user_id=user_id)
        conversation = await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        await self.ensure_idle(db=db, conversation_id=conversation_id)
        if conversation.source == obj.source:
            return 0
        self.check_revision(conversation=conversation, expected=obj.expected_revision)
        await ai_buddy_conversation_audit_service.record(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
            action=AIBuddyConversationAuditAction.migrate,
            detail={'from': conversation.source, 'to': obj.source},
        )
        return await ai_buddy_conversation_dao.update_source(db, conversation.id, obj.source)

    async def update_workspace(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        obj: UpdateAIBuddyConversationWorkspaceParam,
    ) -> int:
        """
        更新对话所属项目、助手和目标

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param obj: 工作区参数
        :return:
        """
        conversation = await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        self.check_revision(conversation=conversation, expected=obj.expected_revision)
        if obj.project_id is not None:
            project = await ai_buddy_project_dao.get(db, obj.project_id)
            if not project or project.user_id != user_id:
                raise errors.NotFoundError(msg='项目不存在')
        if obj.assistant_id is not None:
            assistant = await ai_buddy_assistant_dao.get_by_id_and_user_id(db, obj.assistant_id, user_id)
            if not assistant:
                raise errors.NotFoundError(msg='助手不存在')
        goal = obj.goal.strip() if obj.goal else None
        if goal is not None and len(goal) > 512:
            raise errors.RequestError(msg='对话目标过长')
        previous_assistant_id = conversation.assistant_id
        count = await ai_buddy_conversation_dao.update_workspace(
            db,
            conversation.id,
            project_id=obj.project_id,
            assistant_id=obj.assistant_id,
            goal=goal or None,
        )
        if obj.assistant_id is not None and obj.assistant_id != previous_assistant_id:
            await ai_buddy_assistant_service.record_usage(db=db, pk=obj.assistant_id)
        return count

    async def fork(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        message_id: int | None = None,
        include_message: bool = True,
    ) -> str:
        """
        复刻对话及其消息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param message_id: 分支锚点消息 ID
        :param include_message: 是否包含锚点消息
        :return:
        """
        conversation = await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        boundary = None
        if message_id is not None:
            boundary = await ai_buddy_message_dao.get(db, message_id)
            if boundary is None or boundary.conversation_id != conversation_id:
                raise errors.NotFoundError(msg='消息不存在')
            if boundary.status == AIBuddyMessageStatus.pending:
                raise errors.ConflictError(msg='消息正在生成，请等待完成后复刻')
        new_conversation_id = uuid4_str()
        title = normalize_conversation_title(title=f'{conversation.title} (复刻)', fallback=conversation.title)
        await ai_buddy_conversation_dao.create(
            db,
            CreateAIBuddyConversationParam(
                conversation_id=new_conversation_id,
                title=title[:256],
                provider_id=conversation.provider_id,
                model_id=conversation.model_id,
                user_id=user_id,
                project_id=conversation.project_id,
                assistant_id=conversation.assistant_id,
                goal=conversation.goal,
                origin=conversation.origin,
                surface=conversation.surface,
                agent_mode=conversation.agent_mode,
                last_message_preview=conversation.last_message_preview,
                last_message_time=conversation.last_message_time,
            ),
        )
        await ai_buddy_assistant_service.record_usage(db=db, pk=conversation.assistant_id)
        message_rows = list(await ai_buddy_message_dao.get_all_by_message_index(db, conversation.conversation_id))
        copied_rows = [
            row
            for row in message_rows
            if row.status != AIBuddyMessageStatus.pending
            and (
                boundary is None
                or (row.message_index, row.id) < (boundary.message_index, boundary.id)
                or (include_message and row.id == boundary.id)
            )
        ]
        branch = None
        branch_anchor = None
        if boundary is not None:
            branch_anchor = next(
                (
                    row
                    for row in reversed(message_rows)
                    if row.role == 'user' and (row.message_index, row.id) <= (boundary.message_index, boundary.id)
                ),
                boundary,
            )
            source = (branch_anchor.turn_context or {}).get('branch', {})
            branch = {
                'source_conversation_id': source.get('source_conversation_id', conversation_id),
                'source_message_id': source.get('source_message_id', branch_anchor.id),
                'parent_conversation_id': conversation_id,
                'parent_message_id': boundary.id,
            }
        if copied_rows:
            await ai_buddy_message_dao.bulk_create(
                db,
                [
                    {
                        'conversation_id': new_conversation_id,
                        'provider_id': row.provider_id,
                        'model_id': row.model_id,
                        'message_index': row.message_index,
                        'role': row.role,
                        'model_messages': row.model_messages,
                        'origin': row.origin,
                        'turn_context': (
                            {**(row.turn_context or {}), 'branch': branch}
                            if branch is not None and row.id == branch_anchor.id
                            else row.turn_context
                        ),
                        'status': row.status,
                    }
                    for row in copied_rows
                ],
            )
            await track_copied_attachments(
                db=db,
                conversation_id=new_conversation_id,
                user_id=user_id,
                payloads=[row.model_messages for row in copied_rows],
            )
            forked_rows = await ai_buddy_message_dao.get_all_by_message_index(db, new_conversation_id)
            index_to_new_id = {row.message_index: row.id for row in forked_rows}
            error_rows = await ai_buddy_message_error_dao.get_all_by_message_ids(db, [row.id for row in copied_rows])
            for error in error_rows:
                source_index = next(
                    (row.message_index for row in copied_rows if row.id == error.message_id),
                    None,
                )
                new_message_id = index_to_new_id.get(source_index) if source_index is not None else None
                if new_message_id is None:
                    continue
                await ai_buddy_message_error_dao.create(
                    db,
                    {
                        'message_id': new_message_id,
                        'conversation_id': new_conversation_id,
                        'message': error.message,
                        'detail': error.detail,
                    },
                )
        if branch is not None and not any(row.id == branch_anchor.id for row in copied_rows):
            await ai_buddy_message_dao.create(
                db,
                {
                    'conversation_id': new_conversation_id,
                    'provider_id': boundary.provider_id,
                    'model_id': boundary.model_id,
                    'message_index': (copied_rows[-1].message_index + 1) if copied_rows else 0,
                    'role': 'system',
                    'model_messages': [],
                    'status': AIBuddyMessageStatus.success,
                    'turn_context': {'branch': branch, 'branch_pending': True},
                },
            )
        if boundary is None:
            await copy_conversation_plan(
                user_id=user_id,
                source_conversation_id=conversation.conversation_id,
                target_conversation_id=new_conversation_id,
            )
        else:
            await self.refresh_last_message(db=db, conversation_id=new_conversation_id)
        return new_conversation_id

    async def delete(self, *, db: AsyncSession, conversation_id: str, user_id: int) -> int:
        """
        删除对话，级联策略：消息和错误记录软删除；步骤事件、快照和工具台账立即物理删除；
        附件等对象只释放本对话的引用，无人引用的对象进入墓碑并在宽限期后回收；
        用户产物不随对话删除

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :return:
        """
        await self.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=True,
        )
        await self.ensure_idle(db=db, conversation_id=conversation_id)

        await ai_buddy_message_error_dao.delete_by_conversation_id(db, conversation_id)
        await ai_buddy_message_dao.delete(db, conversation_id)
        await ai_buddy_step_service.delete_by_conversation(db=db, conversation_id=conversation_id)
        await ai_buddy_object_service.release_owner(
            db=db, owner_type='conversation', owner_id=conversation_id, actor_id=user_id
        )
        count = await ai_buddy_conversation_dao.delete(db, conversation_id, user_id)
        await ai_buddy_conversation_audit_service.record(
            db=db, user_id=user_id, conversation_id=conversation_id, action=AIBuddyConversationAuditAction.delete
        )
        await delete_conversation_plan(user_id=user_id, conversation_id=conversation_id)
        await destroy_conversation_sandbox(user_id=user_id, conversation_id=conversation_id)
        return count


ai_buddy_conversation_service: AIBuddyConversationService = AIBuddyConversationService()
