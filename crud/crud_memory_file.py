from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.memory_file import AIBuddyMemoryFile


class CRUDAIBuddyMemoryFile(CRUDPlus[AIBuddyMemoryFile]):
    """AI 记忆文件数据库操作类"""

    async def get_by_path(self, db: AsyncSession, path: str, *, for_update: bool = False) -> AIBuddyMemoryFile | None:
        """
        按路径读取记忆文件，可锁定当前版本

        :param db: 数据库会话
        :param path: 记忆路径
        :param for_update: 是否加行锁
        :return:
        """
        stmt = select(self.model).where(self.model.path == path)
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def save(db: AsyncSession, row: AIBuddyMemoryFile) -> None:
        """
        写入记忆文件并检查唯一约束

        :param db: 数据库会话
        :param row: 记忆文件
        :return:
        """
        db.add(row)
        await db.flush()

    @staticmethod
    async def delete(db: AsyncSession, row: AIBuddyMemoryFile) -> None:
        """
        物理删除记忆文件

        :param db: 数据库会话
        :param row: 记忆文件
        :return:
        """
        await db.delete(row)

    async def get_paths(self, db: AsyncSession, prefix: str, limit: int) -> list[str]:
        """
        按前缀获取记忆路径

        :param db: 数据库会话
        :param prefix: 路径前缀
        :param limit: 数量上限
        :return:
        """
        stmt = select(self.model.path).where(self.model.path.startswith(prefix)).order_by(self.model.path).limit(limit)
        return list((await db.execute(stmt)).scalars().all())

    async def get_contents(self, db: AsyncSession, prefix: str, limit: int) -> Sequence[tuple[str, str]]:
        """
        按路径顺序读取检索所需内容

        :param db: 数据库会话
        :param prefix: 路径前缀
        :param limit: 数量上限
        :return:
        """
        stmt = (
            select(self.model.path, self.model.content)
            .where(self.model.path.startswith(prefix))
            .order_by(self.model.path)
            .limit(limit)
        )
        return (await db.execute(stmt)).tuples().all()


ai_buddy_memory_file_dao: CRUDAIBuddyMemoryFile = CRUDAIBuddyMemoryFile(AIBuddyMemoryFile)
