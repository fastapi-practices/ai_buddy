import asyncio

from collections.abc import Callable
from typing import Any

import anyio

from starlette.concurrency import run_in_threadpool

_KNOWLEDGE_IO_MAX_WORKERS = 2
"""知识文件解析的线程池并发上限"""

_KNOWLEDGE_COMPUTE_MAX_WORKERS = 1
"""文本切块与 ONNX 推理的线程池并发上限"""

_io_limiter = anyio.CapacityLimiter(_KNOWLEDGE_IO_MAX_WORKERS)
"""知识文件 IO 并发限流器"""

_compute_limiter = anyio.CapacityLimiter(_KNOWLEDGE_COMPUTE_MAX_WORKERS)
"""知识计算并发限流器"""

_background_tasks: set[asyncio.Task[Any]] = set()
"""请求取消后仍在后台执行的线程池任务"""


async def _run_in_threadpool[T](
    limiter: anyio.CapacityLimiter,
    func: Callable[..., T],
    /,
    *args: Any,
    **kwargs: Any,
) -> T:
    """
    在限流器保护下把同步调用交给 Starlette 线程池执行

    限流器名额由本函数持有，调用方取消后线程池任务仍持有名额直到线程结束

    :param limiter: 并发限流器
    :param func: 同步函数
    :param args: 位置参数
    :param kwargs: 关键字参数
    :return:
    """
    async with limiter:
        return await run_in_threadpool(func, *args, **kwargs)


async def _run_detached[T](
    limiter: anyio.CapacityLimiter,
    func: Callable[..., T],
    /,
    *args: Any,
    **kwargs: Any,
) -> T:
    """
    执行线程池调用并在请求取消时立即向上抛出取消异常

    线程池任务不会被强制终止，会继续执行到结束，
    并发名额在底层线程真正结束后才释放

    :param limiter: 并发限流器
    :param func: 同步函数
    :param args: 位置参数
    :param kwargs: 关键字参数
    :return:
    """
    task = asyncio.ensure_future(_run_in_threadpool(limiter, func, *args, **kwargs))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    # 请求取消后任务异常无人接收，取出异常避免运行时告警
    task.add_done_callback(lambda finished: finished.cancelled() or finished.exception())

    return await asyncio.shield(task)


async def run_blocking_io[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """
    在受控并发下把同步 IO 调用交给 Starlette 线程池执行

    :param func: 同步函数
    :param args: 位置参数
    :param kwargs: 关键字参数
    :return:
    """
    return await _run_detached(_io_limiter, func, *args, **kwargs)


async def run_blocking_compute[T](func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """
    在受控并发下把同步计算调用交给 Starlette 线程池执行

    :param func: 同步函数
    :param args: 位置参数
    :param kwargs: 关键字参数
    :return:
    """
    return await _run_detached(_compute_limiter, func, *args, **kwargs)


async def shutdown_blocking_io_tasks(timeout: float = 5.0) -> None:
    """
    取消请求取消后遗留的后台线程池任务

    :param timeout: 等待任务结束的秒数
    :return:
    """
    tasks = tuple(_background_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=timeout)
