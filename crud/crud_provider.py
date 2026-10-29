from collections.abc import Sequence

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.common.enums import StatusType
from backend.plugin.ai_buddy.model import AIBuddyProvider
from backend.plugin.ai_buddy.schema.provider import CreateAIBuddyProviderParam, UpdateAIBuddyProviderParam
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID, is_visible_owner, visible_owner_ids
from backend.utils.timezone import timezone


class CRUDAIBuddyProvider(CRUDPlus[AIBuddyProvider]):
    """AI 供应商数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyProvider | None:
        """
        获取供应商

        :param db: 数据库会话
        :param pk: 供应商 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_visible(self, db: AsyncSession, pk: int, user_id: int) -> AIBuddyProvider | None:
        """
        获取当前用户可见的供应商

        :param db: 数据库会话
        :param pk: 供应商 ID
        :param user_id: 用户 ID
        :return:
        """
        provider = await self.get(db, pk)
        if provider is None or not is_visible_owner(owner_id=provider.user_id, user_id=user_id):
            return None
        return provider

    async def get_by_name(self, db: AsyncSession, user_id: int, name: str) -> AIBuddyProvider | None:
        """
        通过名称获取当前用户供应商

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param name: 供应商名称
        :return:
        """
        return await self.select_model_by_column(db, user_id=user_id, name=name, deleted=0)

    async def get_by_ids(self, db: AsyncSession, pks: list[int]) -> Sequence[AIBuddyProvider]:
        """
        批量获取供应商

        :param db: 数据库会话
        :param pks: 供应商 ID 列表
        :return:
        """
        return await self.select_models(db, id__in=pks, deleted=0)

    async def get_select(self, name: str | None, type: int | None, status: int | None) -> Select:
        """
        获取供应商列表查询表达式

        :param name: 供应商名称
        :param type: 供应商类型
        :param status: 状态
        :return:
        """
        filters: dict[str, object] = {'deleted': 0, 'user_id': SYSTEM_OWNER_USER_ID}
        if name is not None:
            filters['name__like'] = f'%{name}%'
        if type is not None:
            filters['type'] = type
        if status is not None:
            filters['status'] = status
        return await self.select_order('id', 'desc', **filters)

    async def get_all(self, db: AsyncSession, *, user_id: int | None = None) -> Sequence[AIBuddyProvider]:
        """
        获取启用的供应商

        :param db: 数据库会话
        :param user_id: 用户 ID，空则只返回系统内置
        :return:
        """
        filters: dict[str, object] = {'status': StatusType.enable.value, 'deleted': 0}
        if user_id is None:
            filters['user_id'] = SYSTEM_OWNER_USER_ID
        else:
            filters['user_id__in'] = visible_owner_ids(user_id)
        return await self.select_models_order(db, 'id', 'desc', **filters)

    async def get_all_owned(self, db: AsyncSession, user_id: int) -> Sequence[AIBuddyProvider]:
        """
        获取当前用户自己的供应商

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self.select_models_order(db, 'id', 'desc', user_id=user_id, deleted=0)

    async def create(
        self,
        db: AsyncSession,
        obj: CreateAIBuddyProviderParam,
        user_id: int = SYSTEM_OWNER_USER_ID,
    ) -> AIBuddyProvider:
        """
        创建供应商

        :param db: 数据库会话
        :param obj: 创建供应商参数
        :param user_id: 用户 ID
        :return:
        """
        return await self.create_model(db, obj, user_id=user_id, flush=True)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyProviderParam) -> int:
        """
        更新供应商

        :param db: 数据库会话
        :param pk: 供应商 ID
        :param obj: 更新供应商参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pks: list[int]) -> int:
        """
        批量删除供应商

        :param db: 数据库会话
        :param pks: 供应商 ID 列表
        :return:
        """
        return await self.delete_model_by_column(
            db,
            allow_multiple=True,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id__in=pks,
            deleted=0,
        )


ai_buddy_provider_dao: CRUDAIBuddyProvider = CRUDAIBuddyProvider(AIBuddyProvider)
