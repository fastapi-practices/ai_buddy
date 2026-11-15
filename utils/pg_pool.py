import asyncio

import asyncpg

from backend.common.log import log
from backend.core.conf import settings

_POOL_MIN_SIZE = 1
_POOL_MAX_SIZE = 10
_pool: asyncpg.Pool | None = None
_pool_lock = asyncio.Lock()


async def get_pg_pool() -> asyncpg.Pool:
    """
    获取插件共享的 PostgreSQL 连接池

    Pydantic AI 的 PostgresMemoryStore 需要 asyncpg 连接池，不能直接复用 SQLAlchemy Engine

    :return:
    """
    global _pool
    if _pool is not None:
        return _pool
    async with _pool_lock:
        if _pool is None:
            _pool = await asyncpg.create_pool(
                host=settings.DATABASE_HOST,
                port=settings.DATABASE_PORT,
                user=settings.DATABASE_USER,
                password=settings.DATABASE_PASSWORD or None,
                database=settings.DATABASE_SCHEMA,
                min_size=_POOL_MIN_SIZE,
                max_size=_POOL_MAX_SIZE,
                command_timeout=60,
                server_settings={'application_name': 'fba-ai-buddy'},
            )
        return _pool


async def close_pg_pool() -> None:
    """关闭插件共享连接池"""
    global _pool
    if _pool is None:
        return
    pool, _pool = _pool, None
    try:
        await pool.close()
    except Exception as exc:
        log.warning(f'关闭 AI Buddy PostgreSQL 连接池失败: {exc}')
