from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model.channel_user import AIBuddyChannelUser


class CRUDAIBuddyChannelUser(CRUDPlus[AIBuddyChannelUser]):
    """AI 通道用户映射数据库操作类"""

    async def get_by_external_id(
        self, db: AsyncSession, channel_id: int, external_id: str
    ) -> AIBuddyChannelUser | None:
        """
        获取通道用户映射

        :param db: 数据库会话
        :param channel_id: 通道 ID
        :param external_id: 平台用户标识
        :return:
        """
        return await self.select_model_by_column(db, channel_id=channel_id, external_id=external_id, deleted=0)

    async def create(self, db: AsyncSession, channel_id: int, user_id: int, external_id: str) -> AIBuddyChannelUser:
        """
        创建通道用户映射

        :param db: 数据库会话
        :param channel_id: 通道 ID
        :param user_id: 系统用户 ID
        :param external_id: 平台用户标识
        :return:
        """
        mapping = self.model(channel_id=channel_id, user_id=user_id, external_id=external_id)
        db.add(mapping)
        await db.flush()
        return mapping

    async def update_extra(self, db: AsyncSession, pk: int, extra: dict[str, Any]) -> int:
        """
        更新外部会话的绑定信息

        :param db: 数据库会话
        :param pk: 映射 ID
        :param extra: 绑定信息
        :return:
        """
        return await self.update_model_by_column(db, {'extra': extra}, id=pk, deleted=0)


ai_buddy_channel_user_dao: CRUDAIBuddyChannelUser = CRUDAIBuddyChannelUser(AIBuddyChannelUser)
