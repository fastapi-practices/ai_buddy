import asyncio

from pydantic_ai_harness.memory import PostgresMemoryStore

from backend.common.log import log
from backend.plugin.ai_buddy.utils.pg_pool import get_pg_pool

_MEMORY_TABLE = 'ai_buddy_memory'
_MIGRATION_LOCK = 'ai_buddy_memory_legacy_migration'
_store: PostgresMemoryStore | None = None
_store_lock = asyncio.Lock()


async def _migrate_legacy_memory() -> None:
    """
    将旧版 SQLAlchemy 记忆表复制到 Pydantic AI 的 PostgreSQL 存储

    :return:
    """
    pool = await get_pg_pool()
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute('select pg_advisory_xact_lock(hashtext($1))', _MIGRATION_LOCK)
        legacy = await connection.fetchval("select to_regclass('ai_buddy_memory_file') is not null")
        if not legacy:
            return
        migrated = await connection.fetch(
            f'insert into {_MEMORY_TABLE} (path, content, version, last_operation_id) '
            'select path, content, version, last_operation_id from ai_buddy_memory_file '
            'on conflict (path) do nothing returning path'
        )
        await connection.execute(
            f"select setval('{_MEMORY_TABLE}_versions', greatest("
            f'(select last_value from {_MEMORY_TABLE}_versions), '
            f'coalesce((select max(version) from {_MEMORY_TABLE}), 0)), true)'
        )
        if await connection.fetchval("select to_regclass('ai_buddy_memory_operation') is not null"):
            await connection.execute(
                f'insert into {_MEMORY_TABLE}_operations (id, fingerprint, version, existed, completed) '
                'select operation_id, fingerprint, version, existed, completed from ai_buddy_memory_operation '
                'on conflict (id) do nothing'
            )
    if migrated:
        log.info(f'已迁移 {len(migrated)} 个旧版 AI Buddy 记忆文件')


def reset_memory_store() -> None:
    """释放当前进程缓存的记忆存储"""
    global _store
    _store = None


async def get_memory_store() -> PostgresMemoryStore:
    """
    获取 Pydantic AI PostgreSQL 记忆存储，首次调用时建表并迁移旧数据

    :return:
    """
    global _store
    if _store is not None:
        return _store
    async with _store_lock:
        if _store is None:
            pool = await get_pg_pool()
            store = PostgresMemoryStore(pool, table=_MEMORY_TABLE)
            # 建表后再迁移，旧表不存在时不影响全新安装
            await store.list_paths('', limit=1)
            try:
                await _migrate_legacy_memory()
            except Exception as exc:
                log.warning(f'迁移旧版 AI Buddy 记忆失败: {exc}')
            _store = store
        return _store
