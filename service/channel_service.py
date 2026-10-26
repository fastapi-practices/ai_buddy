import re

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.ai_buddy.crud.crud_channel import ai_buddy_channel_dao
from backend.plugin.ai_buddy.enums import AIBuddyChannelType
from backend.plugin.ai_buddy.model.channel import AIBuddyChannel
from backend.plugin.ai_buddy.schema.channel import CreateAIBuddyChannelParam, UpdateAIBuddyChannelParam
from backend.plugin.ai_buddy.utils.sensitive_data import restore_masked_sensitive_data


class AIBuddyChannelService:
    """AI 通道服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyChannel]:
        """
        获取当前用户所有通道

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await ai_buddy_channel_dao.get_all(db, user_id)

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int) -> AIBuddyChannel:
        """
        获取通道详情

        :param db: 数据库会话
        :param pk: 通道 ID
        :param user_id: 用户 ID
        :return:
        """
        channel = await ai_buddy_channel_dao.get(db, pk)
        if channel is None or channel.user_id != user_id:
            raise errors.NotFoundError(msg='通道不存在')
        return channel

    async def create(self, *, db: AsyncSession, obj: CreateAIBuddyChannelParam, user_id: int) -> None:
        """
        创建通道

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        obj = self._normalize(obj=obj)
        if await ai_buddy_channel_dao.get_by_name(db, user_id, obj.name):
            raise errors.ConflictError(msg='通道名称已存在')
        await ai_buddy_channel_dao.create(db, obj, user_id)

    async def update(self, *, db: AsyncSession, pk: int, obj: UpdateAIBuddyChannelParam, user_id: int) -> int:
        """
        更新通道

        :param db: 数据库会话
        :param pk: 通道 ID
        :param obj: 更新参数
        :param user_id: 用户 ID
        :return:
        """
        channel = await self.get(db=db, pk=pk, user_id=user_id)
        obj = obj.model_copy(update={'config': restore_masked_sensitive_data(obj.config, channel.config)})
        obj = self._normalize(obj=obj)
        existed = await ai_buddy_channel_dao.get_by_name(db, user_id, obj.name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='通道名称已存在')
        return await ai_buddy_channel_dao.update(db, pk, obj)

    async def delete(self, *, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除通道

        :param db: 数据库会话
        :param pk: 通道 ID
        :param user_id: 用户 ID
        :return:
        """
        channel = await self.get(db=db, pk=pk, user_id=user_id)
        return await ai_buddy_channel_dao.delete(db, pk, channel.user_id)

    @staticmethod
    def _normalize(
        *, obj: CreateAIBuddyChannelParam | UpdateAIBuddyChannelParam
    ) -> CreateAIBuddyChannelParam | UpdateAIBuddyChannelParam:
        """
        规范化通道字段

        :param obj: 创建或更新参数
        :return:
        """
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='通道名称不能为空')
        config = obj.config
        if obj.type == AIBuddyChannelType.discord:
            config = dict(obj.config or {})
            allow_all_channels = config.setdefault('allow_all_channels', True)
            if not isinstance(allow_all_channels, bool):
                raise errors.RequestError(msg='允许所有可访问频道必须为布尔值')
            for key, label in (
                ('allowed_channel_ids', '允许的频道 ID'),
                ('allowed_user_ids', '允许私聊的用户 ID'),
            ):
                values = config.get(key, [])
                if isinstance(values, str):
                    values = re.split(r'[,，\n\r]+', values)
                if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                    raise errors.RequestError(msg=f'{label}必须为字符串列表')
                normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
                if any(not value.isascii() or not value.isdecimal() for value in normalized):
                    raise errors.RequestError(msg=f'{label}仅支持数字 ID')
                config[key] = normalized
        return obj.model_copy(update={'name': name, 'config': config})


ai_buddy_channel_service: AIBuddyChannelService = AIBuddyChannelService()
