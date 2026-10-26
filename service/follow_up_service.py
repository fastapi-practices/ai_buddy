import asyncio

from datetime import timedelta

from ag_ui.core import UserMessage
from sqlalchemy.ext.asyncio import AsyncSession
from starlette_context import request_cycle_context

from backend.app.admin.crud.crud_user import user_dao
from backend.common.context import ctx
from backend.common.exception import errors
from backend.common.log import log
from backend.database.db import async_db_session, uuid4_str
from backend.plugin.ai_buddy.agent.coding.execution_bridge import get_bridge as get_execution_bridge
from backend.plugin.ai_buddy.agent.coding.protocol.acp.bridge import get_bridge as get_acp_bridge
from backend.plugin.ai_buddy.agent.work.runs import has_active_run
from backend.plugin.ai_buddy.crud.crud_follow_up import ai_buddy_follow_up_dao
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyConversationSurface,
    AIBuddyExecutionBackend,
    AIBuddyFollowUpMode,
    AIBuddyFollowUpStatus,
    AIBuddyMessageRole,
)
from backend.plugin.ai_buddy.model.conversation import AIBuddyConversation
from backend.plugin.ai_buddy.model.follow_up import AIBuddyFollowUp
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam
from backend.plugin.ai_buddy.schema.chat_base import AIBuddyRunAgentInput
from backend.plugin.ai_buddy.schema.follow_up import (
    GetAIBuddyFollowUpDetail,
    GetAIBuddyFollowUpsDetail,
    SubmitAIBuddyFollowUpParam,
    UpdateAIBuddyFollowUpParam,
)
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.utils.timezone import timezone

_STEER_REASON = '当前运行时未暴露可确认的实时引导接口，已降级为持久排队'
_CLAIM_TIMEOUT_SECONDS = 120
_LOCAL_BRIDGE_REASON = (
    '本地执行跟进无法派发：桌面执行连接缺失、已断开或已在上一轮结束后关闭（连接仅供单轮使用）'
    '，请在桌面端重新连接，用新的 executionBridgeId 和 clientRequestId 重新提交'
)
_ACP_BRIDGE_REASON = (
    'ACP 跟进无法派发：本地 Agent 连接缺失、已断开或已在上一轮结束后关闭（连接仅供单轮使用）'
    '，请在桌面端重新连接，用新的 acpBridgeId 和 clientRequestId 重新提交'
)


class AIBuddyFollowUpService:
    """持久跟进提交与后台派发"""

    @staticmethod
    async def _owned(
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        lock: bool = False,
        require_active: bool = False,
    ) -> AIBuddyConversation:
        """
        校验会话归属和跟进可用状态

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param lock: 是否锁定会话记录
        :param require_active: 是否要求会话未归档
        :return:
        """
        conversation = await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            for_update=lock,
        )
        if conversation.surface != AIBuddyConversationSurface.chat:
            raise errors.RequestError(msg='跟进队列仅支持聊天会话')
        if require_active and conversation.archived_time is not None:
            raise errors.ConflictError(msg='对话已归档，请恢复后再提交跟进')
        return conversation

    async def submit(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        obj: SubmitAIBuddyFollowUpParam,
    ) -> GetAIBuddyFollowUpDetail:
        """
        锁定会话后幂等提交

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param obj: 请求参数
        :return:
        """
        conversation = await self._owned(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            lock=True,
            require_active=True,
        )
        ai_buddy_conversation_service.validate_agent_mode(
            conversation=conversation, forwarded_props=obj.forwarded_props
        )
        forwarded_props = ai_buddy_conversation_service.resolve_work_location(
            forwarded_props=obj.forwarded_props,
            message_rows=await ai_buddy_message_dao.get_all_by_message_index(db, conversation_id),
        )
        existing = await ai_buddy_follow_up_dao.get_by_request_id(db, conversation_id, obj.client_request_id)
        if existing is not None:
            if existing.deleted:
                raise errors.ConflictError(msg='该跟进已删除，请使用新的 clientRequestId')
            return GetAIBuddyFollowUpDetail.model_validate(existing)
        rows = await ai_buddy_follow_up_dao.get_list(db, conversation_id, for_update=True)
        position = sum(row.status == AIBuddyFollowUpStatus.queued for row in rows)
        row = AIBuddyFollowUp(
            conversation_id=conversation_id,
            user_id=user_id,
            client_request_id=obj.client_request_id,
            content=obj.content,
            attachments=[item.model_dump(mode='json', by_alias=True) for item in obj.attachments],
            forwarded_props=forwarded_props.model_dump(mode='json', by_alias=True),
            user_context={
                'user_id': user_id,
                'is_superuser': bool(ctx.is_superuser),
                'language': ctx.language or 'zh-CN',
            },
            mode=obj.mode,
            position=position,
            reason=_STEER_REASON if obj.mode == AIBuddyFollowUpMode.steer else None,
        )
        await ai_buddy_follow_up_dao.create(db, row)
        return GetAIBuddyFollowUpDetail.model_validate(row)

    async def get_list(self, *, db: AsyncSession, conversation_id: str, user_id: int) -> GetAIBuddyFollowUpsDetail:
        """
        获取所属会话跟进记录

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :return:
        """
        await self._owned(db=db, conversation_id=conversation_id, user_id=user_id)
        rows = await ai_buddy_follow_up_dao.get_list(db, conversation_id)
        return GetAIBuddyFollowUpsDetail(items=[GetAIBuddyFollowUpDetail.model_validate(row) for row in rows])

    async def _editable(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        followup_id: int,
    ) -> tuple[AIBuddyFollowUp, list[AIBuddyFollowUp]]:
        """
        锁定并获取可编辑的排队跟进

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param followup_id: 跟进 ID
        :return:
        """
        await self._owned(db=db, conversation_id=conversation_id, user_id=user_id, lock=True)
        rows = await ai_buddy_follow_up_dao.get_list(db, conversation_id, for_update=True)
        row = next((item for item in rows if item.id == followup_id and item.user_id == user_id), None)
        if row is None:
            raise errors.NotFoundError(msg='跟进不存在')
        if row.status != AIBuddyFollowUpStatus.queued:
            raise errors.ConflictError(msg='仅可修改或删除排队中的跟进')
        return row, [item for item in rows if item.status == AIBuddyFollowUpStatus.queued]

    async def update(
        self,
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        followup_id: int,
        obj: UpdateAIBuddyFollowUpParam,
    ) -> GetAIBuddyFollowUpDetail:
        """
        修改内容或移动待执行项

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param followup_id: 跟进 ID
        :param obj: 请求参数
        :return:
        """
        row, queued = await self._editable(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            followup_id=followup_id,
        )
        values = obj.model_dump(mode='json', by_alias=False, exclude_unset=True)
        position = values.pop('position', None)
        updated = SubmitAIBuddyFollowUpParam.model_validate({
            'client_request_id': row.client_request_id,
            'mode': row.mode,
            'content': row.content,
            'attachments': row.attachments,
            'forwarded_props': row.forwarded_props,
            **values,
        })
        conversation = await self._owned(db=db, conversation_id=conversation_id, user_id=user_id)
        ai_buddy_conversation_service.validate_agent_mode(
            conversation=conversation, forwarded_props=updated.forwarded_props
        )
        forwarded_props = ai_buddy_conversation_service.resolve_work_location(
            forwarded_props=updated.forwarded_props,
            message_rows=await ai_buddy_message_dao.get_all_by_message_index(db, conversation_id),
        )
        row.content = updated.content
        row.attachments = [item.model_dump(mode='json', by_alias=True) for item in updated.attachments]
        row.forwarded_props = forwarded_props.model_dump(mode='json', by_alias=True)
        if position is not None:
            if position >= len(queued):
                raise errors.RequestError(msg='队列位置超出范围')
            queued.remove(row)
            queued.insert(position, row)
        self._renumber(rows=queued)
        await db.flush()
        return GetAIBuddyFollowUpDetail.model_validate(row)

    async def delete(self, *, db: AsyncSession, conversation_id: str, user_id: int, followup_id: int) -> None:
        """
        保留幂等墓碑并删除待执行项

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param followup_id: 跟进 ID
        :return:
        """
        row, queued = await self._editable(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            followup_id=followup_id,
        )
        row.deleted = row.id
        row.deleted_time = timezone.now()
        queued.remove(row)
        self._renumber(rows=queued)
        await db.flush()

    @staticmethod
    def _renumber(*, rows: list[AIBuddyFollowUp]) -> None:
        """
        按当前队列顺序更新位置

        :param rows: 记录列表
        :return:
        """
        for position, row in enumerate(rows):
            row.position = position

    async def claim(self, *, conversation_id: str) -> AIBuddyFollowUp | None:
        """
        认领下一项，事务锁协调多个服务进程

        :param conversation_id: 对话 ID
        :return:
        """
        async with async_db_session.begin() as db:
            rows = await ai_buddy_follow_up_dao.get_list(db, conversation_id)
            if not rows:
                return None
            try:
                conversation = await self._owned(
                    db=db,
                    conversation_id=conversation_id,
                    user_id=rows[0].user_id,
                    lock=True,
                )
            except errors.NotFoundError:
                rows = await ai_buddy_follow_up_dao.get_list(db, conversation_id, for_update=True)
                for row in rows:
                    if row.status == AIBuddyFollowUpStatus.queued or (
                        row.status == AIBuddyFollowUpStatus.dispatched and not row.dispatch_committed
                    ):
                        row.status = AIBuddyFollowUpStatus.failed.value
                        row.reason = '所属对话已删除'
                return None
            if conversation.archived_time is not None or await has_active_run(conversation_id):
                return None
            # 锁等待后重新读取，避免按旧状态认领
            rows = await ai_buddy_follow_up_dao.get_list(db, conversation_id, for_update=True)
            for row in rows:
                if row.status == AIBuddyFollowUpStatus.dispatched and not row.dispatch_committed:
                    if row.claimed_time is None or row.claimed_time > timezone.now() - timedelta(
                        seconds=_CLAIM_TIMEOUT_SECONDS
                    ):
                        return None
                    row.status = AIBuddyFollowUpStatus.failed.value
                    row.reason = '派发未确认完成，未自动重放；请检查会话后重新提交'
            queued = [row for row in rows if row.status == AIBuddyFollowUpStatus.queued]
            if not queued:
                return None
            row = queued.pop(0)
            row.status = AIBuddyFollowUpStatus.dispatched.value
            row.run_id = uuid4_str()
            row.claimed_time = timezone.now()
            self._renumber(rows=queued)
            await db.flush()
            db.expunge(row)
            return row

    async def dispatch(self, *, conversation_id: str) -> None:  # ruff: ignore[complex-structure]
        """
        用当前账号权限启动后台运行，不依赖流订阅者

        :param conversation_id: 对话 ID
        :return:
        """
        from backend.plugin.ai_buddy.service.chat_service import ai_buddy_chat_service

        row = await self.claim(conversation_id=conversation_id)
        if row is None:
            return
        failure_reason = '跟进派发失败，请检查运行参数和账号权限后重新提交'
        try:
            async with async_db_session() as db:
                user = await user_dao.get(db, row.user_id)
                if user is None or user.deleted or user.status != 1:
                    raise errors.RequestError(msg='提交用户已停用或删除')
                user_context = {
                    **row.user_context,
                    'user_id': row.user_id,
                    'is_superuser': bool(user.is_superuser and row.user_context.get('is_superuser')),
                }
            forwarded_props = AIBuddyChatForwardedPropsParam.model_validate(row.forwarded_props)
            bridge_reason = None
            if forwarded_props.agent_mode == AIBuddyAgentMode.coding:
                if forwarded_props.acp_runner:
                    if not forwarded_props.acp_bridge_id or not forwarded_props.acp_runner_name:
                        bridge_reason = _ACP_BRIDGE_REASON
                    else:
                        try:
                            await get_acp_bridge(
                                bridge_id=forwarded_props.acp_bridge_id,
                                user_id=row.user_id,
                                runner=forwarded_props.acp_runner_name,
                            )
                        except errors.RequestError:
                            bridge_reason = _ACP_BRIDGE_REASON
                elif forwarded_props.execution_backend == AIBuddyExecutionBackend.local:
                    if not forwarded_props.execution_bridge_id:
                        bridge_reason = _LOCAL_BRIDGE_REASON
                    else:
                        try:
                            await get_execution_bridge(
                                bridge_id=forwarded_props.execution_bridge_id,
                                user_id=row.user_id,
                                backend=AIBuddyExecutionBackend.local,
                                permission_mode=forwarded_props.permission_mode,
                            )
                        except errors.RequestError:
                            bridge_reason = _LOCAL_BRIDGE_REASON
            if bridge_reason is not None:
                failure_reason = bridge_reason
                raise errors.RequestError(msg=bridge_reason)
            run_input = AIBuddyRunAgentInput(
                thread_id=conversation_id,
                run_id=row.run_id,
                messages=[
                    UserMessage.model_validate({
                        'id': row.client_request_id,
                        'role': AIBuddyMessageRole.user,
                        'content': [{'type': 'text', 'text': row.content}, *row.attachments]
                        if row.attachments
                        else row.content,
                    })
                ],
                tools=[],
                context=[],
                forwarded_props=forwarded_props.model_dump(mode='json', by_alias=True),
            )
            with request_cycle_context(user_context):
                await ai_buddy_chat_service.run_completion(
                    user_id=row.user_id,
                    run_input=run_input,
                    assistant_id=None,
                    forwarded_props=forwarded_props,
                    accept=None,
                    empty_message_error='跟进内容不能为空',
                    followup_id=row.id,
                )
        except Exception as exc:
            async with async_db_session.begin() as db:
                await self._owned(db=db, conversation_id=conversation_id, user_id=row.user_id, lock=True)
                current = await ai_buddy_follow_up_dao.get(db, row.id)
                if (
                    current is not None
                    and current.run_id == row.run_id
                    and current.status == AIBuddyFollowUpStatus.dispatched
                    and not current.dispatch_committed
                ):
                    if isinstance(exc, errors.ConflictError):
                        rows = await ai_buddy_follow_up_dao.get_list(db, conversation_id, for_update=True)
                        current.status = AIBuddyFollowUpStatus.queued.value
                        current.run_id = None
                        current.claimed_time = None
                        self._renumber(
                            rows=[
                                current,
                                *(
                                    item
                                    for item in rows
                                    if item.status == AIBuddyFollowUpStatus.queued and item.id != row.id
                                ),
                            ]
                        )
                    else:
                        current.status = AIBuddyFollowUpStatus.failed.value
                        current.reason = failure_reason
            log.warning(f'跟进派发失败 followup_id={row.id}: {exc}')

    async def run_worker(self) -> None:
        """扫描持久队列，重启后继续执行待排队项"""
        tasks: dict[str, asyncio.Task[None]] = {}
        try:
            while True:
                tasks = {key: task for key, task in tasks.items() if not task.done()}
                try:
                    async with async_db_session() as db:
                        conversations = await ai_buddy_follow_up_dao.get_due_conversations(db)
                    for conversation_id in conversations:
                        if conversation_id not in tasks:
                            tasks[conversation_id] = asyncio.create_task(
                                self._dispatch_safely(conversation_id=conversation_id),
                                name=f'ai-buddy-follow-up-{conversation_id}',
                            )
                except Exception as exc:
                    log.warning(f'扫描跟进队列失败: {exc}')
                await asyncio.sleep(1)
        finally:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    async def _dispatch_safely(self, *, conversation_id: str) -> None:
        """
        派发跟进并记录后台任务异常

        :param conversation_id: 对话 ID
        :return:
        """
        try:
            await self.dispatch(conversation_id=conversation_id)
        except Exception as exc:
            log.warning(f'跟进调度失败 conversation_id={conversation_id}: {exc}')


ai_buddy_follow_up_service = AIBuddyFollowUpService()
