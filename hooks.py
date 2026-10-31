import asyncio

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.exceptions import LockError

from backend.common.log import log
from backend.common.redaction import redaction
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.database.redis import redis_client
from backend.plugin.ai_buddy.agent.work.runs import shutdown_runs as shutdown_chat_runs
from backend.plugin.ai_buddy.cron.tasks import tick_due_crons
from backend.plugin.ai_buddy.schema.object import AIBuddyObjectGarbageCollectParam
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.service.follow_up_service import ai_buddy_follow_up_service
from backend.plugin.ai_buddy.service.gateway_channel_service import ai_buddy_gateway_channel_service
from backend.plugin.ai_buddy.service.knowledge_service import ai_buddy_knowledge_service
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service
from backend.plugin.ai_buddy.service.skill_service import ai_buddy_skill_service
from backend.plugin.ai_buddy.utils.knowledge_reindex import register_reindex_runner
from backend.plugin.ai_buddy.utils.skill_parser import load_builtin_skill_payloads

_RECONCILE_INTERVAL_SECONDS = 30
_CRON_INTERVAL_SECONDS = 60
_BUILTIN_SKILL_RETRY_SECONDS = 300


async def _reconcile_stale_pending_loop() -> None:
    """周期清理长期 pending 的输入请求"""
    while True:
        try:
            chat_count = await ai_buddy_conversation_service.reconcile_stale_pending()
            if chat_count:
                log.info(f'已收敛 {chat_count} 条残留聊天消息')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(f'扫描残留聊天消息失败: {exc}')
        await asyncio.sleep(_RECONCILE_INTERVAL_SECONDS)


async def _cron_tick_loop() -> None:
    """周期触发到期 cron 任务"""
    while True:
        try:
            delivered = await tick_due_crons()
            if delivered:
                log.info(f'已执行 {delivered} 条定时任务')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(f'扫描定时任务失败: {exc}')
        await asyncio.sleep(_CRON_INTERVAL_SECONDS)


async def _builtin_skill_sync_loop() -> None:
    """周期同步内置技能包"""
    while True:
        try:
            synced = 0
            for payloads in load_builtin_skill_payloads():
                async with async_db_session.begin() as db:
                    if await ai_buddy_skill_service.sync_builtin(db=db, payloads=payloads):
                        synced += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 默认 S3 存储尚未配置时会落到这里，配置完成后自动补齐
            log.warning(f'同步内置技能失败: {exc}')
        else:
            if synced:
                log.info(f'已写入或升级 {synced} 个内置技能')
            return
        await asyncio.sleep(_BUILTIN_SKILL_RETRY_SECONDS)


async def _object_gc_loop() -> None:
    """周期回收过期对象存储内容"""
    interval = settings.AI_BUDDY_OBJECT_GC_INTERVAL_SECONDS
    lock = redis_client.lock(
        f'{settings.PLUGIN_REDIS_PREFIX}:ai_buddy:object-gc:lock', timeout=max(interval, 60), thread_local=False
    )
    while True:
        try:
            # 多实例同时运行时只有抢到锁的实例执行本轮回收
            if await lock.acquire(blocking=False):
                try:
                    async with async_db_session.begin() as db:
                        result = await ai_buddy_object_service.collect_garbage(
                            db=db, user_id=None, obj=AIBuddyObjectGarbageCollectParam(dry_run=False)
                        )
                finally:
                    await lock.release()
                if result.deleted or result.failed:
                    log.info(f'统一对象回收完成 deleted={len(result.deleted)} failed={len(result.failed)}')
        except asyncio.CancelledError:
            raise
        except LockError as exc:
            log.warning(f'统一对象回收锁异常: {exc}')
        except Exception as exc:
            log.warning(f'统一对象回收失败: {exc}')
        await asyncio.sleep(interval)


def setup(app: FastAPI) -> None:
    """
    注册操作日志、访问日志和校验错误的脱敏规则，避免聊天内容与 OAuth 凭据泄露

    :param app: FastAPI 应用
    :return:
    """
    redaction.register(
        body_paths=[
            r'/input-requests/',
            r'/(?:chat/completions|images/generations|mcps/oauth/callback)/?$',
            r'/mcps/(?:.*/)?oauth(?:/config)?/?$',
        ],
        query_paths=[r'/mcps/oauth/callback/?$'],
        opaque_fields=['messages', 'forwardedprops', 'forwarded_props'],
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    管理聊天后台任务、各平台通道和残留状态收敛，并登记知识索引重建函数

    :param app: FastAPI 应用
    :return:
    """
    register_reindex_runner(ai_buddy_knowledge_service.reindex_default_binding)
    reconcile_task = asyncio.create_task(
        _reconcile_stale_pending_loop(),
        name='ai-chat-stale-pending-reconciler',
    )
    cron_task = asyncio.create_task(_cron_tick_loop(), name='ai-buddy-cron-ticker')
    builtin_skill_task = asyncio.create_task(_builtin_skill_sync_loop(), name='ai-buddy-builtin-skill-sync')
    follow_up_task = asyncio.create_task(ai_buddy_follow_up_service.run_worker(), name='ai-buddy-follow-up-worker')
    gateway_task = asyncio.create_task(ai_buddy_gateway_channel_service.run_worker(), name='ai-buddy-gateway-worker')
    object_gc_task = (
        asyncio.create_task(_object_gc_loop(), name='ai-buddy-object-gc')
        if settings.AI_BUDDY_OBJECT_GC_INTERVAL_SECONDS > 0
        else None
    )
    background = [
        task
        for task in (reconcile_task, cron_task, builtin_skill_task, follow_up_task, gateway_task, object_gc_task)
        if task
    ]
    try:
        yield
    finally:
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await shutdown_chat_runs()
