from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.common.enums import StatusType
from backend.plugin.ai_buddy.enums import AIBuddyChannelType
from backend.plugin.ai_buddy.model.channel import AIBuddyChannel
from backend.plugin.ai_buddy.schema.channel import CreateAIBuddyChannelParam, UpdateAIBuddyChannelParam
from backend.utils.timezone import timezone


class CRUDAIBuddyChannel(CRUDPlus[AIBuddyChannel]):
    """AI 通道数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyChannel | None:
        """
        获取通道

        :param db: 数据库会话
        :param pk: 通道 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_name(self, db: AsyncSession, user_id: int, name: str) -> AIBuddyChannel | None:
        """
        通过名称获取当前用户通道

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 通道名称
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, name=name, deleted=0)

    async def get_for_update(self, db: AsyncSession, pk: int) -> AIBuddyChannel | None:
        """
        锁定通道以串行建立外部用户和会话映射

        :param db: 数据库会话
        :param pk: 通道 ID
        :return:
        """
        stmt = (await self.select(id=pk, deleted=0)).with_for_update()
        return await db.scalar(stmt)

    async def get_all(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyChannel]:
        """
        获取当前用户所有通道

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(db, 'id', 'desc', user_id=user_id, deleted=0)

    async def get_enabled_by_type(self, db: AsyncSession, channel_type: AIBuddyChannelType) -> Sequence[AIBuddyChannel]:
        """
        获取指定类型的启用通道

        :param db: 数据库会话
        :param channel_type: 通道类型
        :return:
        """
        return await self.select_models_order(db, 'id', 'asc', type=channel_type, status=StatusType.enable, deleted=0)

    async def get_enabled_by_types(
        self, db: AsyncSession, channel_types: Sequence[AIBuddyChannelType]
    ) -> Sequence[AIBuddyChannel]:
        """
        获取指定平台的所有启用通道

        :param db: 数据库会话
        :param channel_types: 通道平台
        :return:
        """
        return await self.select_models_order(
            db, 'id', 'asc', type__in=channel_types, status=StatusType.enable, deleted=0
        )

    async def create(self, db: AsyncSession, obj: CreateAIBuddyChannelParam, user_id: int) -> None:
        """
        创建通道

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        await self.create_model(db, obj, user_id=user_id)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyChannelParam) -> int:
        """
        更新通道

        :param db: 数据库会话
        :param pk: 通道 ID
        :param obj: 更新参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除通道

        :param db: 数据库会话
        :param pk: 通道 ID
        :param user_id: 用户 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id=pk,
            user_id=user_id,
            deleted=0,
        )


ai_buddy_channel_dao: CRUDAIBuddyChannel = CRUDAIBuddyChannel(AIBuddyChannel)
