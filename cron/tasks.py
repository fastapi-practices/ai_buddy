import asyncio

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from redis.asyncio.lock import Lock
from redis.exceptions import LockNotOwnedError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette_context import request_cycle_context

from backend.app.admin.crud.crud_user import user_dao
from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.database.db import async_db_session, uuid4_str
from backend.database.redis import redis_client
from backend.plugin.ai_buddy.agent.work.runs import get_local_run
from backend.plugin.ai_buddy.cron.schedule import trigger_is_due
from backend.plugin.ai_buddy.cron.stream import consume_cron_stream
from backend.plugin.ai_buddy.cron.trigger import parse_trigger
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.crud.crud_cron import ai_buddy_cron_dao
from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyOrigin
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam
from backend.plugin.ai_buddy.schema.conversation import CreateAIBuddyConversationParam
from backend.plugin.ai_buddy.service.chat_service import ai_buddy_chat_service
from backend.plugin.ai_buddy.service.cron_service import ai_buddy_cron_service
from backend.plugin.ai_buddy.utils.conversation_title import normalize_generated_conversation_title
from backend.utils.timezone import timezone

_CRON_LOCK_SECONDS = 120
_CRON_LOCK_RENEW_SECONDS = 30
_background_tasks: set[asyncio.Task[None]] = set()


async def _renew_cron_lock(lock: Lock, owner: asyncio.Task) -> None:
    """
    续租跨进程执行锁，失去锁时停止本次派发

    :param lock: 分布式锁
    :param owner: 锁持有者
    :return:
    """
    try:
        while True:
            await asyncio.sleep(_CRON_LOCK_RENEW_SECONDS)
            await lock.extend(_CRON_LOCK_SECONDS, replace_ttl=True)
    except Exception as exc:
        log.warning(f'定时任务执行锁续租失败: {exc}')
        owner.cancel()


@asynccontextmanager
async def _claim_cron_run(cron_id: int) -> AsyncGenerator[bool, None]:
    """
    同一任务只允许一个服务进程执行

    :param cron_id: 定时任务 ID
    :return:
    """
    lock = redis_client.lock(
        f'{settings.PLUGIN_REDIS_PREFIX}:ai_buddy:cron:{cron_id}:lock',
        timeout=_CRON_LOCK_SECONDS,
        thread_local=False,
    )
    if not await lock.acquire(blocking=False):
        yield False
        return
    owner = asyncio.current_task()
    assert owner is not None
    renewal = asyncio.create_task(_renew_cron_lock(lock, owner), name=f'ai-buddy-cron-renew-{cron_id}')
    try:
        yield True
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, return_exceptions=True)
        try:
            await lock.release()
        except LockNotOwnedError:
            log.warning(f'定时任务执行锁已失效 cron_id={cron_id}')


async def _mark_run(
    *,
    cron_id: int,
    status: str,
    error: str | None = None,
    disable: bool = False,
) -> None:
    """
    写入最近执行结果

    :param cron_id: 定时任务 ID
    :param status: 执行状态
    :param error: 错误信息
    :param disable: 是否停用任务
    :return:
    """
    async with async_db_session.begin() as db:
        await ai_buddy_cron_dao.update_run_result(
            db,
            cron_id,
            last_run_time=timezone.now(),
            last_status=status,
            last_error=error,
            status=StatusType.disable if disable else None,
        )


async def deliver_cron_prompt(*, cron_id: int, scheduled: bool = False) -> None:  # ruff: ignore[complex-structure]
    """
    把定时任务提示词投到指定对话跑一轮，origin=cron

    :param cron_id: 定时任务 ID
    :param scheduled: 是否仅执行仍然到期的调度任务
    :return:
    """
    async with _claim_cron_run(cron_id) as claimed:
        if not claimed:
            return
        disable_after = False
        try:
            async with async_db_session() as db:
                cron = await ai_buddy_cron_dao.get(db, cron_id)
                if cron is None or cron.status != StatusType.enable:
                    return
                if scheduled and not trigger_is_due(
                    cron.trigger,
                    now=timezone.now(),
                    last_run_time=cron.last_run_time,
                    created_time=cron.created_time,
                ):
                    return
                user = await user_dao.get(db, cron.user_id)
                if user is None or user.status != StatusType.enable:
                    raise errors.RequestError(msg='定时任务用户已停用或删除')
                user_context = {
                    'user_id': cron.user_id,
                    'is_superuser': bool(user.is_superuser),
                    'language': 'zh-CN',
                }
                conversation = await ai_buddy_conversation_dao.get_by_conversation_id(db, cron.conversation_id)
                if conversation is None or conversation.user_id != cron.user_id:
                    raise errors.NotFoundError(msg='定时任务对话不存在')
                kind, _value = parse_trigger(cron.trigger)
                disable_after = kind == 'date'
                db.expunge(cron)
                db.expunge(conversation)
                snapshot = cron
                target = conversation
            if snapshot.fresh_thread:
                conversation_id = uuid4_str()
                provider_id = snapshot.provider_id or target.provider_id
                model_id = snapshot.model_id or target.model_id
                async with async_db_session.begin() as db:
                    await ai_buddy_conversation_dao.create(
                        db,
                        CreateAIBuddyConversationParam(
                            conversation_id=conversation_id,
                            title=normalize_generated_conversation_title(title=snapshot.prompt),
                            provider_id=provider_id,
                            model_id=model_id,
                            user_id=snapshot.user_id,
                            project_id=target.project_id,
                            assistant_id=target.assistant_id,
                            agent_mode=target.agent_mode,
                            origin=AIBuddyOrigin.cron,
                        ),
                    )
                async with async_db_session() as db:
                    created = await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
                    if created is None:
                        raise errors.NotFoundError(msg='定时任务对话不存在')
                    db.expunge(created)
                    target = created
            with request_cycle_context(user_context):
                forwarded = AIBuddyChatForwardedPropsParam(
                    provider_id=snapshot.provider_id or target.provider_id,
                    model_id=snapshot.model_id or target.model_id,
                    assistant_id=target.assistant_id,
                    mcp_ids=list(snapshot.mcp_ids or []),
                    agent_mode=target.agent_mode or AIBuddyAgentMode.work,
                )
                response = await ai_buddy_chat_service.run_text_prompt(
                    user_id=snapshot.user_id,
                    conversation_id=target.conversation_id,
                    prompt=snapshot.prompt,
                    forwarded_props=forwarded,
                    origin=AIBuddyOrigin.cron,
                    assistant_id=target.assistant_id,
                )
                run = get_local_run(target.conversation_id)
                try:
                    await consume_cron_stream(response)
                    if run is not None and run.cancellation_token.cancelled:
                        raise errors.RequestError(msg='定时任务生成已取消')
                except asyncio.CancelledError:
                    if run is not None:
                        run.cancellation_token.cancel()
                    raise
            await _mark_run(cron_id=cron_id, status='ok', disable=disable_after)
            log.info(f'定时任务已执行 cron_id={cron_id} conversation_id={target.conversation_id}')
        except Exception as exc:
            log.warning(f'定时任务执行失败 cron_id={cron_id}: {exc}')
            try:
                await _mark_run(cron_id=cron_id, status='error', error=str(exc), disable=disable_after)
            except Exception as mark_exc:
                log.warning(f'写入定时任务执行结果失败 cron_id={cron_id}: {mark_exc}')


async def run_cron_now(*, db: AsyncSession, pk: int, user_id: int) -> None:
    """
    校验任务归属和启用状态后在后台立即执行一次，不占用请求连接

    :param db: 数据库会话
    :param pk: 任务 ID
    :param user_id: 用户 ID
    :return:
    """
    cron = await ai_buddy_cron_service.get(db=db, pk=pk, user_id=user_id)
    if cron.status != StatusType.enable:
        raise errors.RequestError(msg='定时任务已停用，请启用后再执行')
    if await redis_client.exists(f'{settings.PLUGIN_REDIS_PREFIX}:ai_buddy:cron:{pk}:lock'):
        raise errors.ConflictError(msg='定时任务正在执行，请稍后再试')
    task = asyncio.create_task(deliver_cron_prompt(cron_id=pk), name=f'ai-buddy-cron-now-{pk}')
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def tick_due_crons() -> int:
    """扫描到期的定时任务并执行"""
    now = timezone.now()
    async with async_db_session() as db:
        rows = await ai_buddy_cron_dao.get_enabled(db)
        due_ids = [
            item.id
            for item in rows
            if trigger_is_due(
                item.trigger,
                now=now,
                last_run_time=item.last_run_time,
                created_time=item.created_time,
            )
        ]
    for cron_id in due_ids:
        task = asyncio.create_task(
            deliver_cron_prompt(cron_id=cron_id, scheduled=True), name=f'ai-buddy-cron-{cron_id}'
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    return len(due_ids)
