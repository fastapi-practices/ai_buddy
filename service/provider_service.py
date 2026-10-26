from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.common.pagination import cursor_paging_data
from backend.plugin.ai_buddy.crud.crud_default_model import ai_buddy_default_model_dao
from backend.plugin.ai_buddy.crud.crud_model import ai_buddy_model_dao
from backend.plugin.ai_buddy.crud.crud_provider import ai_buddy_provider_dao
from backend.plugin.ai_buddy.model import AIBuddyProvider
from backend.plugin.ai_buddy.provider.base import resolve_provider_api_host
from backend.plugin.ai_buddy.provider.registry import get_provider_adapter
from backend.plugin.ai_buddy.schema.provider import (
    CreateAIBuddyProviderParam,
    CreateMyAIBuddyProviderParam,
    DeleteAIBuddyProviderParam,
    GetAIBuddyProviderModelDetail,
    UpdateAIBuddyProviderParam,
    UpdateMyAIBuddyProviderParam,
)
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID
from backend.plugin.ai_buddy.utils.sensitive_data import mask_api_key


class AIBuddyProviderService:
    """AI 供应商服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession) -> Sequence[AIBuddyProvider]:
        """
        获取所有 AI 供应商

        :param db: 数据库会话
        :return:
        """
        return await ai_buddy_provider_dao.get_all(db)

    @staticmethod
    async def get(*, db: AsyncSession, pk: int) -> AIBuddyProvider:
        """
        获取 AI 供应商

        :param db: 数据库会话
        :param pk: 供应商 ID
        :return:
        """
        ai_buddy_provider = await ai_buddy_provider_dao.get(db, pk)
        if not ai_buddy_provider:
            raise errors.NotFoundError(msg='供应商不存在')
        return ai_buddy_provider

    @staticmethod
    async def get_visible(*, db: AsyncSession, pk: int, user_id: int) -> AIBuddyProvider:
        """
        获取当前用户可见的供应商

        :param db: 数据库会话
        :param pk: 供应商 ID
        :param user_id: 用户 ID
        :return:
        """
        ai_buddy_provider = await ai_buddy_provider_dao.get_visible(db, pk, user_id)
        if not ai_buddy_provider:
            raise errors.NotFoundError(msg='供应商不存在')
        return ai_buddy_provider

    @staticmethod
    async def get_mine(*, db: AsyncSession, pk: int, user_id: int) -> AIBuddyProvider:
        """
        获取当前用户自己的供应商

        :param db: 数据库会话
        :param pk: 供应商 ID
        :param user_id: 用户 ID
        :return:
        """
        ai_buddy_provider = await ai_buddy_provider_dao.get(db, pk)
        if ai_buddy_provider is None or ai_buddy_provider.user_id != user_id:
            raise errors.NotFoundError(msg='供应商不存在')
        return ai_buddy_provider

    @staticmethod
    async def get_mine_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyProvider]:
        """
        获取当前用户自己的全部供应商

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await ai_buddy_provider_dao.get_all_owned(db, user_id)

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        name: str | None,
        type: int | None,
        status: int | None,
    ) -> dict[str, Any]:
        """
        获取 AI 供应商列表

        :param db: 数据库会话
        :param name: 供应商名称
        :param type: 供应商类型
        :param status: 状态
        :return:
        """
        ai_buddy_provider_select = await ai_buddy_provider_dao.get_select(name, type, status)
        return await cursor_paging_data(db, ai_buddy_provider_select)

    @staticmethod
    async def create(*, db: AsyncSession, obj: CreateAIBuddyProviderParam) -> None:
        """
        创建平台供应商

        :param db: 数据库会话
        :param obj: 创建供应商参数
        :return:
        """
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='供应商名称不能为空')
        if await ai_buddy_provider_dao.get_by_name(db, SYSTEM_OWNER_USER_ID, name):
            raise errors.ConflictError(msg='供应商名称已存在')
        host = resolve_provider_api_host(obj.type, obj.api_host)
        await ai_buddy_provider_dao.create(
            db,
            obj.model_copy(update={'name': name, 'api_host': host}),
            SYSTEM_OWNER_USER_ID,
        )

    @staticmethod
    async def create_mine(
        *,
        db: AsyncSession,
        obj: CreateMyAIBuddyProviderParam,
        user_id: int,
    ) -> AIBuddyProvider:
        """
        创建当前用户自己的供应商

        :param db: 数据库会话
        :param obj: 创建供应商参数
        :param user_id: 用户 ID
        :return:
        """
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='供应商名称不能为空')
        api_key = obj.api_key.strip()
        if not api_key:
            raise errors.RequestError(msg='接口密钥不能为空')
        if await ai_buddy_provider_dao.get_by_name(db, user_id, name):
            raise errors.ConflictError(msg='供应商名称已存在')
        host = resolve_provider_api_host(obj.type, obj.api_host)
        return await ai_buddy_provider_dao.create(
            db,
            CreateAIBuddyProviderParam(
                name=name,
                type=obj.type,
                api_key=api_key,
                api_host=host,
                status=obj.status,
                remark=obj.remark,
            ),
            user_id,
        )

    async def update(self, *, db: AsyncSession, pk: int, obj: UpdateAIBuddyProviderParam) -> int:
        """
        更新平台供应商

        :param db: 数据库会话
        :param pk: 供应商 ID
        :param obj: 更新供应商参数
        :return:
        """
        ai_buddy_provider = await self.get(db=db, pk=pk)
        if ai_buddy_provider.user_id != SYSTEM_OWNER_USER_ID:
            raise errors.ForbiddenError(msg='用户自建供应商请在客户端修改')
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='供应商名称不能为空')
        existed = await ai_buddy_provider_dao.get_by_name(db, SYSTEM_OWNER_USER_ID, name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='供应商名称已存在')
        host = resolve_provider_api_host(obj.type, obj.api_host)
        update_obj = obj.model_copy(
            update={
                'name': name,
                'api_host': host,
                'api_key': (
                    ai_buddy_provider.api_key
                    if not obj.api_key.strip() or obj.api_key == mask_api_key(ai_buddy_provider.api_key)
                    else obj.api_key
                ),
            }
        )
        return await ai_buddy_provider_dao.update(db, pk, update_obj)

    async def update_mine(
        self,
        *,
        db: AsyncSession,
        pk: int,
        obj: UpdateMyAIBuddyProviderParam,
        user_id: int,
    ) -> int:
        """
        更新当前用户自己的供应商

        :param db: 数据库会话
        :param pk: 供应商 ID
        :param obj: 更新供应商参数
        :param user_id: 用户 ID
        :return:
        """
        ai_buddy_provider = await self.get_mine(db=db, pk=pk, user_id=user_id)
        name = obj.name.strip()
        if not name:
            raise errors.RequestError(msg='供应商名称不能为空')
        existed = await ai_buddy_provider_dao.get_by_name(db, user_id, name)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='供应商名称已存在')
        host = resolve_provider_api_host(obj.type, obj.api_host)
        update_obj = UpdateAIBuddyProviderParam(
            name=name,
            type=obj.type,
            api_key=(
                ai_buddy_provider.api_key
                if not obj.api_key.strip() or obj.api_key == mask_api_key(ai_buddy_provider.api_key)
                else obj.api_key.strip()
            ),
            api_host=host,
            status=obj.status,
            remark=obj.remark,
        )
        return await ai_buddy_provider_dao.update(db, pk, update_obj)

    @staticmethod
    async def delete(*, db: AsyncSession, obj: DeleteAIBuddyProviderParam) -> int:
        """
        删除平台供应商

        :param db: 数据库会话
        :param obj: 供应商 ID 列表
        :return:
        """
        providers = await ai_buddy_provider_dao.get_by_ids(db, obj.pks)
        if any(provider.user_id != SYSTEM_OWNER_USER_ID for provider in providers):
            raise errors.ForbiddenError(msg='用户自建供应商请在客户端删除')
        await ai_buddy_default_model_dao.delete_by_providers(db, obj.pks)
        await ai_buddy_model_dao.delete_by_providers(db, obj.pks)
        return await ai_buddy_provider_dao.delete(db, obj.pks)

    @staticmethod
    async def delete_mine(*, db: AsyncSession, obj: DeleteAIBuddyProviderParam, user_id: int) -> int:
        """
        删除当前用户自己的供应商及其模型

        :param db: 数据库会话
        :param obj: 供应商 ID 列表
        :param user_id: 用户 ID
        :return:
        """
        providers = await ai_buddy_provider_dao.get_by_ids(db, obj.pks)
        if {provider.id for provider in providers} != set(obj.pks):
            raise errors.NotFoundError(msg='供应商不存在')
        if any(provider.user_id != user_id for provider in providers):
            raise errors.NotFoundError(msg='供应商不存在')
        await ai_buddy_default_model_dao.delete_by_providers(db, obj.pks)
        await ai_buddy_model_dao.delete_by_providers(db, obj.pks)
        return await ai_buddy_provider_dao.delete(db, obj.pks)

    @staticmethod
    async def _list_models(*, provider: AIBuddyProvider) -> list[GetAIBuddyProviderModelDetail]:
        """
        获取指定供应商的远程模型列表

        :param provider: 供应商
        :return:
        """
        if provider.status != StatusType.enable:
            raise errors.RequestError(msg='当前供应商已停用，无法获取模型列表')
        adapter = get_provider_adapter(provider.type)
        snapshots = await adapter.list_models(api_key=provider.api_key, api_host=provider.api_host)
        return [
            GetAIBuddyProviderModelDetail(
                id=snapshot.id,
                object=snapshot.object,
                created=snapshot.created,
                display_name=snapshot.display_name,
                kind=snapshot.kind,
                capabilities=list(snapshot.capabilities),
                input_modalities=list(snapshot.input_modalities),
                context_window=snapshot.context_window,
                max_output_tokens=snapshot.max_output_tokens,
            )
            for snapshot in snapshots
        ]

    async def get_models(self, *, db: AsyncSession, pk: int) -> list[GetAIBuddyProviderModelDetail]:
        """
        获取供应商模型

        :param db: 数据库会话
        :param pk: 供应商 ID
        :return:
        """
        ai_buddy_provider = await self.get(db=db, pk=pk)
        return await self._list_models(provider=ai_buddy_provider)

    async def get_mine_models(
        self,
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
    ) -> list[GetAIBuddyProviderModelDetail]:
        """
        获取当前用户供应商的远程模型列表

        :param db: 数据库会话
        :param pk: 供应商 ID
        :param user_id: 用户 ID
        :return:
        """
        ai_buddy_provider = await self.get_mine(db=db, pk=pk, user_id=user_id)
        return await self._list_models(provider=ai_buddy_provider)


ai_buddy_provider_service: AIBuddyProviderService = AIBuddyProviderService()
