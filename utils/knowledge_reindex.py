import asyncio

from collections.abc import Awaitable, Callable

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from backend.common.log import log

_PENDING_REINDEX_KEY = 'ai_buddy_knowledge_reindex_pending'

# 重建函数由插件启动时登记，调度方不依赖知识服务，避免配置层反向依赖业务层
_reindex_runners: list[Callable[[], Awaitable[None]]] = []
# 事件循环只持有任务的弱引用，运行中的重建任务需要在这里保持强引用
_running_tasks: set[asyncio.Task[None]] = set()


def register_reindex_runner(runner: Callable[[], Awaitable[None]]) -> None:
    """
    登记知识索引重建函数

    :param runner: 重建函数，使用独立事务
    :return:
    """
    if runner not in _reindex_runners:
        _reindex_runners.append(runner)


def schedule_reindex(*, db: AsyncSession | None = None) -> None:
    """
    调度知识索引重建，指定会话时等待当前事务提交

    :param db: 默认模型更新使用的数据库会话
    :return:
    """
    if db is not None and db.in_transaction():
        session = db.sync_session
        if not event.contains(session, 'after_commit', _schedule_committed_reindex):
            event.listen(session, 'after_commit', _schedule_committed_reindex)
            event.listen(session, 'after_rollback', _discard_rolled_back_reindex)
            event.listen(session, 'after_transaction_end', _clear_finished_reindex)
        transaction = session.get_nested_transaction() or session.get_transaction()
        if transaction is not None:
            pending: set[SessionTransaction] = session.info.setdefault(_PENDING_REINDEX_KEY, set())
            pending.add(transaction)
            return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_run_reindex_runners())
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)


async def _run_reindex_runners() -> None:
    """后台依次执行已登记的重建函数，单个失败只记录日志"""
    if not _reindex_runners:
        log.warning('知识索引重建未执行：没有登记重建函数')
    for runner in tuple(_reindex_runners):
        try:
            await runner()
        except Exception as exc:
            log.warning(f'知识索引重建失败: {exc}')


def _schedule_committed_reindex(session: Session) -> None:
    """
    最外层事务提交后启动重建，保存点提交只合并请求

    :param session: 事务会话
    :return:
    """
    pending: set[SessionTransaction] | None = session.info.get(_PENDING_REINDEX_KEY)
    if not pending:
        return
    transaction = session.get_nested_transaction()
    if transaction is not None:
        if transaction in pending:
            pending.remove(transaction)
            if transaction.parent is not None:
                pending.add(transaction.parent)
        return
    session.info.pop(_PENDING_REINDEX_KEY, None)
    schedule_reindex()


def _discard_rolled_back_reindex(session: Session) -> None:
    """
    丢弃回滚事务内的重建请求

    :param session: 事务会话
    :return:
    """
    transaction = session.get_nested_transaction()
    if transaction is None:
        session.info.pop(_PENDING_REINDEX_KEY, None)
    else:
        pending: set[SessionTransaction] | None = session.info.get(_PENDING_REINDEX_KEY)
        if pending is not None:
            pending.discard(transaction)


def _clear_finished_reindex(session: Session, transaction: SessionTransaction) -> None:
    """
    事务结束后清理请求，避免关闭会话后复用遗留状态

    :param session: 事务会话
    :param transaction: 事务
    :return:
    """
    if transaction.parent is None:
        session.info.pop(_PENDING_REINDEX_KEY, None)
