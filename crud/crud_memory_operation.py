from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.memory_operation import AIBuddyMemoryOperation


class CRUDAIBuddyMemoryOperation(CRUDPlus[AIBuddyMemoryOperation]):
    """AI 记忆操作回执数据库操作类"""

    async def get_by_operation_id(
        self, db: AsyncSession, operation_id: str, *, for_update: bool = False
    ) -> AIBuddyMemoryOperation | None:
        """
        获取操作回执

        :param db: 数据库会话
        :param operation_id: 操作 ID
        :param for_update: 是否加行锁
        :return:
        """
        stmt = select(self.model).where(self.model.operation_id == operation_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    async def create(self, db: AsyncSession, operation_id: str, fingerprint: str) -> None:
        """
        预占操作回执

        :param db: 数据库会话
        :param operation_id: 操作 ID
        :param fingerprint: 参数指纹
        :return:
        """
        db.add(self.model(operation_id=operation_id, fingerprint=fingerprint))
        await db.flush()

    async def complete(self, db: AsyncSession, operation_id: str, *, version: str | None, existed: bool) -> None:
        """
        完成操作回执

        :param db: 数据库会话
        :param operation_id: 操作 ID
        :param version: 结果版本
        :param existed: 操作前是否存在
        :return:
        """
        await db.execute(
            update(self.model)
            .where(self.model.operation_id == operation_id)
            .values(version=version, existed=existed, completed=True)
        )


ai_buddy_memory_operation_dao: CRUDAIBuddyMemoryOperation = CRUDAIBuddyMemoryOperation(AIBuddyMemoryOperation)
