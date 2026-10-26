from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, String, cast
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.enums import AIBuddyModelCapability
from backend.plugin.ai_buddy.model import AIBuddyModel, AIBuddyProvider
from backend.plugin.ai_buddy.schema.model import CreateAIBuddyModelParam, UpdateAIBuddyModelParam
from backend.plugin.ai_buddy.utils.model_catalog import has_model_capability
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID
from backend.utils.timezone import timezone


class CRUDAIBuddyModel(CRUDPlus[AIBuddyModel]):
    """AI 模型数据库操作类"""

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyModel | None:
        """
        获取模型

        :param db: 数据库会话
        :param pk: 模型 ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_model_and_provider(self, db: AsyncSession, model_id: str, provider_id: int) -> AIBuddyModel | None:
        """
        通过模型和供应商获取模型

        :param db: 数据库会话
        :param model_id: 模型
        :param provider_id: 供应商
        :return:
        """
        return await self.select_model_by_column(db, model_id=model_id, provider_id=provider_id, deleted=0)

    async def get_by_ids(self, db: AsyncSession, pks: list[int]) -> Sequence[AIBuddyModel]:
        """
        批量获取模型

        :param db: 数据库会话
        :param pks: 模型 ID 列表
        :return:
        """
        return await self.select_models(db, id__in=pks, deleted=0)

    async def get_by_provider_model_pairs(
        self, db: AsyncSession, pairs: list[tuple[int, str]]
    ) -> Sequence[AIBuddyModel]:
        """
        批量获取已存在的模型

        :param db: 数据库会话
        :param pairs: 供应商 ID 与模型 ID 组合列表
        :return:
        """
        if not pairs:
            return []

        provider_ids = list({provider_id for provider_id, _ in pairs})
        model_ids = list({model_id for _, model_id in pairs})
        pair_set = set(pairs)
        models = await self.select_models(db, provider_id__in=provider_ids, model_id__in=model_ids, deleted=0)
        return [model for model in models if (model.provider_id, model.model_id) in pair_set]

    async def get_select(
        self,
        provider_id: int | None,
        model_id: str | None,
        status: int | None,
        kind: str | None = None,
        capability: str | None = None,
    ) -> Select:
        """
        获取模型列表查询表达式

        :param provider_id: 供应商 ID
        :param model_id: 模型 ID
        :param status: 状态
        :param kind: 模型类型
        :param capability: 模型能力
        :return:
        """
        filters = {'deleted': 0}
        if provider_id is not None:
            filters['provider_id'] = provider_id
        if model_id is not None:
            filters['model_id__like'] = f'%{model_id}%'
        if status is not None:
            filters['status'] = status
        if kind is not None:
            filters['kind'] = kind
        stmt = await self.select_order(['sort', 'id'], ['asc', 'desc'], **filters)
        stmt = stmt.join(AIBuddyProvider, AIBuddyProvider.id == self.model.provider_id).where(
            AIBuddyProvider.user_id == SYSTEM_OWNER_USER_ID,
            AIBuddyProvider.deleted == 0,
        )
        if capability is not None:
            stmt = stmt.where(cast(self.model.capabilities, String).like(f'%"{capability}"%'))
        return stmt

    async def get_all(
        self,
        db: AsyncSession,
        provider_id: int,
        *,
        status: int | None = None,
        kind: str | None = None,
        capability: str | None = None,
    ) -> Sequence[AIBuddyModel]:
        """
        获取所有模型

        :param db: 数据库会话
        :param provider_id: 供应商 ID
        :param status: 状态
        :param kind: 模型类型
        :param capability: 模型能力
        :return:
        """
        filters = {'provider_id': provider_id, 'deleted': 0}
        if status is not None:
            filters['status'] = status
        if kind is not None:
            filters['kind'] = kind

        models = await self.select_models_order(db, ['sort', 'id'], ['asc', 'desc'], **filters)
        if capability is None:
            return models
        wanted = AIBuddyModelCapability(capability)
        return [model for model in models if has_model_capability(model, wanted)]

    async def get_all_by_providers(
        self,
        db: AsyncSession,
        provider_ids: list[int],
        *,
        status: int | None = None,
    ) -> Sequence[AIBuddyModel]:
        """
        通过供应商 ID 列表获取所有模型

        :param db: 数据库会话
        :param provider_ids: 供应商 ID 列表
        :param status: 状态
        :return:
        """
        if not provider_ids:
            return []
        filters = {'provider_id__in': provider_ids, 'deleted': 0}
        if status is not None:
            filters['status'] = status
        return await self.select_models_order(db, ['sort', 'id'], ['asc', 'desc'], **filters)

    async def create(self, db: AsyncSession, obj: CreateAIBuddyModelParam) -> AIBuddyModel:
        """
        创建模型

        :param db: 数据库会话
        :param obj: 创建模型参数
        :return:
        """
        return await self.create_model(
            db,
            obj,
            flush=True,
            thinking_policy=None if obj.thinking_policy is None else obj.thinking_policy.model_dump(mode='json'),
        )

    async def bulk_create(self, db: AsyncSession, objs: list[dict[str, Any]]) -> None:
        """
        批量创建模型

        :param db: 数据库会话
        :param objs: 批量创建模型参数
        :return:
        """
        now = timezone.now()
        payloads = [
            {
                **obj,
                'created_time': obj.get('created_time', now),
            }
            for obj in objs
        ]
        await self.bulk_create_models(db, payloads)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyModelParam) -> int:
        """
        更新模型

        :param db: 数据库会话
        :param pk: 模型 ID
        :param obj: 更新模型参数
        :return:
        """
        return await self.update_model_by_column(db, obj.model_dump(mode='json', exclude_unset=True), id=pk, deleted=0)

    async def update_architecture(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyModelParam) -> int:
        """
        更新模型架构配置

        :param db: 数据库会话
        :param pk: 模型 ID
        :param obj: 校验后的模型参数
        :return:
        """
        payload = obj.model_dump(
            mode='json',
            include={
                'kind',
                'capabilities',
                'input_modalities',
                'thinking_policy',
                'context_window',
                'max_output_tokens',
            },
        )
        return await self.update_model_by_column(db, payload, allow_multiple=True, id=pk, deleted=0)

    async def delete(self, db: AsyncSession, pks: list[int]) -> int:
        """
        批量删除模型

        :param db: 数据库会话
        :param pks: 模型 ID 列表
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

    async def delete_by_providers(self, db: AsyncSession, provider_ids: list[int]) -> int:
        """
        通过供应商 ID 列表批量删除模型

        :param db: 数据库会话
        :param provider_ids: 供应商 ID 列表
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
            provider_id__in=provider_ids,
            deleted=0,
        )


ai_buddy_model_dao: CRUDAIBuddyModel = CRUDAIBuddyModel(AIBuddyModel)
