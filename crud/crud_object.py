from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.enums import AIBuddyObjectState
from backend.plugin.ai_buddy.model.object import AIBuddyObject


class CRUDAIBuddyObject(CRUDPlus[AIBuddyObject]):
    """AI 统一对象数据库操作类"""

    async def get_owned(self, db: AsyncSession, pk: int, user_id: int) -> AIBuddyObject | None:
        """
        获取当前用户的对象

        :param db: 数据库会话
        :param pk: 对象 ID
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_model_by_column(db, id=pk, user_id=user_id)

    async def get_by_key(
        self, db: AsyncSession, location: str, storage_id: int | None, object_key: str
    ) -> AIBuddyObject | None:
        """
        通过位置和对象键获取对象

        :param db: 数据库会话
        :param location: 对象位置
        :param storage_id: 对象存储 ID
        :param object_key: 对象键
        :return:
        """
        stmt = select(self.model).where(self.model.location == location, self.model.object_key == object_key)
        stmt = stmt.where(
            self.model.storage_id.is_(None) if storage_id is None else self.model.storage_id == storage_id
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_garbage_candidates(
        self, db: AsyncSession, *, now: datetime, user_id: int | None, limit: int
    ) -> Sequence[AIBuddyObject]:
        """
        获取宽限期已过且无引用的墓碑对象

        :param db: 数据库会话
        :param now: 当前时间
        :param user_id: 用户 ID，为空时扫描全部用户
        :param limit: 返回条数
        :return:
        """
        stmt = select(self.model).where(
            self.model.state == AIBuddyObjectState.tombstoned.value,
            self.model.ref_count == 0,
            self.model.delete_after_time <= now,
        )
        if user_id is not None:
            stmt = stmt.where(self.model.user_id == user_id)
        return (await db.execute(stmt.order_by(self.model.id.asc()).limit(limit))).scalars().all()

    @staticmethod
    async def create(db: AsyncSession, obj: AIBuddyObject) -> None:
        """
        创建对象

        :param db: 数据库会话
        :param obj: 对象记录
        :return:
        """
        db.add(obj)
        await db.flush()


ai_buddy_object_dao: CRUDAIBuddyObject = CRUDAIBuddyObject(AIBuddyObject)
