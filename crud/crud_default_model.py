from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.enums import AIBuddyModelKind
from backend.plugin.ai_buddy.model import AIBuddyDefaultModel
from backend.plugin.ai_buddy.schema.default_model import UpdateAIBuddyDefaultModelParam
from backend.utils.timezone import timezone


class CRUDAIBuddyDefaultModel(CRUDPlus[AIBuddyDefaultModel]):
    """AI 默认模型数据库操作类"""

    async def get_by_kind(self, db: AsyncSession, kind: AIBuddyModelKind) -> AIBuddyDefaultModel | None:
        """
        通过模型类型获取默认模型

        :param db: 数据库会话
        :param kind: 模型类型
        :return:
        """
        return await self.select_model_by_column(db, kind=kind.value, deleted=0)

    async def create(self, db: AsyncSession, kind: AIBuddyModelKind, obj: UpdateAIBuddyDefaultModelParam) -> None:
        """
        创建默认模型

        :param db: 数据库会话
        :param kind: 模型类型
        :param obj: 默认模型配置参数
        :return:
        """
        await self.create_model(db, obj, kind=kind.value)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyDefaultModelParam) -> int:
        """
        更新默认模型

        :param db: 数据库会话
        :param pk: 默认模型 ID
        :param obj: 默认模型配置参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def delete_by_provider_model_pairs(self, db: AsyncSession, pairs: list[tuple[int, str]]) -> int:
        """
        通过供应商 ID 与模型 ID 组合批量删除默认模型

        :param db: 数据库会话
        :param pairs: 供应商 ID 与模型 ID 组合列表
        :return:
        """
        if not pairs:
            return 0

        provider_ids = list({provider_id for provider_id, _ in pairs})
        model_ids = list({model_id for _, model_id in pairs})
        pair_set = set(pairs)
        default_models = await self.select_models(db, provider_id__in=provider_ids, model_id__in=model_ids, deleted=0)
        default_model_ids = [model.id for model in default_models if (model.provider_id, model.model_id) in pair_set]
        if not default_model_ids:
            return 0

        return await self.delete_model_by_column(
            db,
            allow_multiple=True,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id__in=default_model_ids,
            deleted=0,
        )

    async def delete_by_providers(self, db: AsyncSession, provider_ids: list[int]) -> int:
        """
        通过供应商 ID 列表批量删除默认模型

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


ai_buddy_default_model_dao: CRUDAIBuddyDefaultModel = CRUDAIBuddyDefaultModel(AIBuddyDefaultModel)
