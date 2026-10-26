from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.object_ref import AIBuddyObjectRef


class CRUDAIBuddyObjectRef(CRUDPlus[AIBuddyObjectRef]):
    """AI 统一对象引用数据库操作类"""

    async def get_by_owner(
        self, db: AsyncSession, object_id: int, owner_type: str, owner_id: str
    ) -> AIBuddyObjectRef | None:
        """
        获取指定引用方的引用

        :param db: 数据库会话
        :param object_id: 对象 ID
        :param owner_type: 引用方类型
        :param owner_id: 引用方 ID
        :return:
        """
        return await self.select_model_by_column(db, object_id=object_id, owner_type=owner_type, owner_id=owner_id)

    async def get_all_by_owner(self, db: AsyncSession, owner_type: str, owner_id: str) -> Sequence[AIBuddyObjectRef]:
        """
        获取指定引用方持有的全部引用

        :param db: 数据库会话
        :param owner_type: 引用方类型
        :param owner_id: 引用方 ID
        :return:
        """
        stmt = select(self.model).where(self.model.owner_type == owner_type, self.model.owner_id == owner_id)
        return (await db.execute(stmt.order_by(self.model.id.asc()))).scalars().all()

    @staticmethod
    async def count(db: AsyncSession, object_id: int) -> int:
        """
        统计对象的引用数

        :param db: 数据库会话
        :param object_id: 对象 ID
        :return:
        """
        stmt = select(func.count()).select_from(AIBuddyObjectRef).where(AIBuddyObjectRef.object_id == object_id)
        return (await db.execute(stmt)).scalar_one()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyObjectRef) -> None:
        """
        创建引用

        :param db: 数据库会话
        :param obj: 引用
        :return:
        """
        db.add(obj)
        await db.flush()

    @staticmethod
    async def delete_by_owner(db: AsyncSession, object_id: int, owner_type: str, owner_id: str) -> int:
        """
        删除指定引用方的引用

        :param db: 数据库会话
        :param object_id: 对象 ID
        :param owner_type: 引用方类型
        :param owner_id: 引用方 ID
        :return:
        """
        stmt = delete(AIBuddyObjectRef).where(
            AIBuddyObjectRef.object_id == object_id,
            AIBuddyObjectRef.owner_type == owner_type,
            AIBuddyObjectRef.owner_id == owner_id,
        )
        return (await db.execute(stmt)).rowcount


ai_buddy_object_ref_dao: CRUDAIBuddyObjectRef = CRUDAIBuddyObjectRef(AIBuddyObjectRef)
