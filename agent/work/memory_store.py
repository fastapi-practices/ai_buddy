import asyncio

from pydantic_ai_harness.memory import (
    MemoryConflictError,
    MemoryFile,
    MemoryMutation,
    MemoryOperation,
    MemoryOperationConflictError,
    MemorySearchResult,
)
from pydantic_ai_harness.memory._store import lexical_search, validate_store_path, validate_store_prefix
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.db import async_db_session
from backend.plugin.ai_buddy.crud.crud_memory_file import ai_buddy_memory_file_dao
from backend.plugin.ai_buddy.crud.crud_memory_operation import ai_buddy_memory_operation_dao
from backend.plugin.ai_buddy.model.memory_file import AIBuddyMemoryFile
from backend.plugin.ai_buddy.utils.qdrant_store import delete_memory_vector, search_memory_points, upsert_memory_vector
from backend.plugin.ai_buddy.utils.text_vector import hash_embed


class DatabaseMemoryStore:
    """基于 SQLAlchemy 的记忆存储，兼容 MySQL 与 PostgreSQL"""

    @staticmethod
    async def _get_operation(
        *,
        db: AsyncSession,
        operation: MemoryOperation,
        for_update: bool = False,
    ) -> MemoryMutation | None:
        """
        读取并校验记忆操作的幂等回执

        :param db: 数据库会话
        :param operation: 幂等操作
        :param for_update: 是否锁定记录
        :return:
        """
        row = await ai_buddy_memory_operation_dao.get_by_operation_id(db, operation.id, for_update=for_update)
        if row is None:
            return None
        if row.fingerprint != operation.fingerprint:
            raise MemoryOperationConflictError(f'operation id {operation.id!r} was reused with different arguments')
        if not row.completed:
            return None
        return MemoryMutation(version=row.version, replayed=True, existed=row.existed)

    async def _reserve_operation(self, *, db: AsyncSession, operation: MemoryOperation) -> MemoryMutation | None:
        """
        预占记忆操作并处理并发重放

        :param db: 数据库会话
        :param operation: 幂等操作
        :return:
        """
        receipt = await self._get_operation(db=db, operation=operation, for_update=True)
        if receipt is not None:
            return receipt
        try:
            async with db.begin_nested():
                await ai_buddy_memory_operation_dao.create(db, operation.id, operation.fingerprint)
        except IntegrityError:
            receipt = await self._get_operation(db=db, operation=operation, for_update=True)
            if receipt is None:
                raise RuntimeError(f'operation {operation.id!r} did not produce a committed receipt')
            return receipt
        return None

    @staticmethod
    async def read(path: str, *, max_chars: int) -> MemoryFile | None:
        """
        按字符上限读取记忆文件

        :param path: 文件路径
        :param max_chars: 最大字符数
        :return:
        """
        validate_store_path(path)
        if max_chars <= 0:
            raise ValueError('max_chars must be positive')
        async with async_db_session.begin() as db:
            row = await ai_buddy_memory_file_dao.get_by_path(db, path)
        if row is None:
            return None
        return MemoryFile(
            content=row.content[:max_chars],
            version=str(row.version),
            operation_id=row.last_operation_id,
            truncated=len(row.content) > max_chars,
        )

    async def get_operation(self, operation: MemoryOperation) -> MemoryMutation | None:
        """
        读取已完成的记忆操作回执

        :param operation: 幂等操作
        :return:
        """
        async with async_db_session.begin() as db:
            return await self._get_operation(db=db, operation=operation)

    async def write(
        self,
        path: str,
        content: str,
        *,
        expected_version: str | None,
        operation: MemoryOperation | None = None,
    ) -> MemoryMutation:
        """
        按预期版本写入记忆文件并同步向量

        :param path: 文件路径
        :param content: 文本内容
        :param expected_version: 预期版本
        :param operation: 幂等操作
        :return:
        """
        validate_store_path(path)
        async with async_db_session.begin() as db:
            if operation is not None:
                receipt = await self._reserve_operation(db=db, operation=operation)
                if receipt is not None:
                    return receipt
            row = await ai_buddy_memory_file_dao.get_by_path(db, path, for_update=True)
            current = str(row.version) if row is not None else None
            if current != expected_version:
                raise MemoryConflictError(f'memory path {path!r} changed before it could be written')
            version = 1 if row is None else row.version + 1
            existed = row is not None
            if row is None:
                row = AIBuddyMemoryFile(
                    path=path,
                    content=content,
                    version=version,
                    last_operation_id=operation.id if operation else None,
                )
            else:
                row.content = content
                row.version = version
                row.last_operation_id = operation.id if operation else None
            try:
                await ai_buddy_memory_file_dao.save(db, row)
            except IntegrityError as exc:
                raise MemoryConflictError(f'memory path {path!r} changed before it could be written') from exc
            mutation = MemoryMutation(version=str(version), replayed=False, existed=existed)
            if operation is not None:
                await ai_buddy_memory_operation_dao.complete(
                    db, operation.id, version=mutation.version, existed=mutation.existed
                )
        try:
            embedding = await asyncio.to_thread(hash_embed, content)
            await upsert_memory_vector(path=path, content=content, embedding=embedding)
        except Exception:
            pass
        return mutation

    async def delete(
        self,
        path: str,
        *,
        expected_version: str | None,
        operation: MemoryOperation | None = None,
    ) -> MemoryMutation:
        """
        按预期版本删除记忆文件并清理向量

        :param path: 文件路径
        :param expected_version: 预期版本
        :param operation: 幂等操作
        :return:
        """
        validate_store_path(path)
        async with async_db_session.begin() as db:
            if operation is not None:
                receipt = await self._reserve_operation(db=db, operation=operation)
                if receipt is not None:
                    return receipt
            row = await ai_buddy_memory_file_dao.get_by_path(db, path, for_update=True)
            current = str(row.version) if row is not None else None
            if current != expected_version:
                raise MemoryConflictError(f'memory path {path!r} changed before it could be deleted')
            existed = row is not None
            if row is not None:
                await ai_buddy_memory_file_dao.delete(db, row)
            mutation = MemoryMutation(version=None, replayed=False, existed=existed)
            if operation is not None:
                await ai_buddy_memory_operation_dao.complete(
                    db, operation.id, version=mutation.version, existed=mutation.existed
                )
        try:
            await delete_memory_vector(path=path)
        except Exception:
            pass
        return mutation

    @staticmethod
    async def list_paths(prefix: str = '', *, limit: int) -> list[str]:
        """
        按前缀列出记忆文件路径

        :param prefix: 路径前缀
        :param limit: 数量上限
        :return:
        """
        validate_store_prefix(prefix)
        if limit <= 0:
            raise ValueError('limit must be positive')
        async with async_db_session.begin() as db:
            return await ai_buddy_memory_file_dao.get_paths(db, prefix, limit)

    @staticmethod
    async def search(
        prefix: str,
        query: str,
        *,
        limit: int,
        max_files: int,
        max_chars: int,
        max_file_chars: int,
    ) -> MemorySearchResult:
        """
        检索前缀范围内的记忆内容

        :param prefix: 路径前缀
        :param query: 检索内容
        :param limit: 数量上限
        :param max_files: 最大文件数
        :param max_chars: 最大字符数
        :param max_file_chars: 单文件最大字符数
        :return:
        """
        validate_store_prefix(prefix)
        if not query.split() or limit <= 0 or max_files <= 0 or max_chars <= 0 or max_file_chars <= 0:
            return MemorySearchResult(matches=[], scanned=0, truncated=False)
        async with async_db_session.begin() as db:
            rows = await ai_buddy_memory_file_dao.get_contents(db, prefix, max_files + 1)
        files = [(str(path), content[:max_file_chars]) for path, content in rows]
        result = await asyncio.to_thread(
            lexical_search,
            files,
            query,
            limit=limit,
            max_files=max_files,
            max_chars=max_chars,
            score_prefix=prefix,
        )
        truncated = result.truncated or any(len(content) > max_file_chars for _, content in rows)
        try:
            query_vector = await asyncio.to_thread(hash_embed, query)
            await search_memory_points(query_vector=query_vector, prefix=prefix, limit=limit)
        except Exception:
            pass
        return MemorySearchResult(matches=result.matches, scanned=result.scanned, truncated=truncated)


database_memory_store: DatabaseMemoryStore = DatabaseMemoryStore()
