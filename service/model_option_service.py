from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.plugin.ai_buddy.crud.crud_default_model import ai_buddy_default_model_dao
from backend.plugin.ai_buddy.crud.crud_model import ai_buddy_model_dao
from backend.plugin.ai_buddy.crud.crud_provider import ai_buddy_provider_dao
from backend.plugin.ai_buddy.enums import AIBuddyModelKind
from backend.plugin.ai_buddy.model import AIBuddyDefaultModel, AIBuddyModel, AIBuddyProvider
from backend.plugin.ai_buddy.schema.default_model import GetAIBuddyDefaultModelDetail
from backend.plugin.ai_buddy.schema.model import GetAIBuddyModelDetail
from backend.plugin.ai_buddy.schema.model_option import (
    GetAIBuddyModelOptionDetail,
    GetAIBuddyProviderModelOptionDetail,
)
from backend.plugin.ai_buddy.utils.model_catalog import eligible_for_default


class AIBuddyModelOptionService:
    """AI 模型选项服务类"""

    async def get_all(self, *, db: AsyncSession, user_id: int) -> GetAIBuddyModelOptionDetail:
        """
        获取模型选项

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        providers = await ai_buddy_provider_dao.get_all(db, user_id=user_id)
        provider_by_id = {provider.id: provider for provider in providers}
        chat_default = await ai_buddy_default_model_dao.get_by_kind(db, AIBuddyModelKind.chat)
        embedding_default = await ai_buddy_default_model_dao.get_by_kind(db, AIBuddyModelKind.embedding)
        image_default = await ai_buddy_default_model_dao.get_by_kind(db, AIBuddyModelKind.image)
        models = await ai_buddy_model_dao.get_all_by_providers(
            db,
            [provider.id for provider in providers],
            status=StatusType.enable.value,
        )
        models_by_provider: dict[int, list[GetAIBuddyModelDetail]] = {provider.id: [] for provider in providers}
        model_by_pair: dict[tuple[int, str], AIBuddyModel] = {}
        for model in models:
            model_by_pair[model.provider_id, model.model_id] = model
            if model.status == StatusType.enable:
                models_by_provider[model.provider_id].append(GetAIBuddyModelDetail.model_validate(model))

        default_candidates = {
            kind: [
                model.id
                for model in models
                if (provider := provider_by_id.get(model.provider_id)) is not None
                and eligible_for_default(kind=kind, provider=provider, model=model)
            ]
            for kind in (AIBuddyModelKind.chat, AIBuddyModelKind.embedding, AIBuddyModelKind.image)
        }
        provider_options = [
            GetAIBuddyProviderModelOptionDetail(
                id=provider.id,
                user_id=provider.user_id,
                name=provider.name,
                type=provider.type,
                status=provider.status,
                models=models_by_provider[provider.id],
            )
            for provider in providers
        ]
        return GetAIBuddyModelOptionDetail(
            providers=provider_options,
            default_candidates=default_candidates,
            default_models={
                AIBuddyModelKind.chat: self._build_default_detail(
                    kind=AIBuddyModelKind.chat,
                    default_model=chat_default,
                    provider_by_id=provider_by_id,
                    model_by_pair=model_by_pair,
                ),
                AIBuddyModelKind.embedding: self._build_default_detail(
                    kind=AIBuddyModelKind.embedding,
                    default_model=embedding_default,
                    provider_by_id=provider_by_id,
                    model_by_pair=model_by_pair,
                ),
                AIBuddyModelKind.image: self._build_default_detail(
                    kind=AIBuddyModelKind.image,
                    default_model=image_default,
                    provider_by_id=provider_by_id,
                    model_by_pair=model_by_pair,
                ),
            },
        )

    @staticmethod
    def _build_default_detail(
        *,
        kind: AIBuddyModelKind,
        default_model: AIBuddyDefaultModel | None,
        provider_by_id: dict[int, AIBuddyProvider],
        model_by_pair: dict[tuple[int, str], AIBuddyModel],
    ) -> GetAIBuddyDefaultModelDetail | None:
        """
        组装已启用且类型匹配的默认模型配置

        :param kind: 模型类型
        :param default_model: 默认模型记录
        :param provider_by_id: 供应商映射
        :param model_by_pair: 供应商与模型组合映射
        :return:
        """
        if default_model is None or default_model.status != StatusType.enable:
            return None
        provider = provider_by_id.get(default_model.provider_id)
        model = model_by_pair.get((default_model.provider_id, default_model.model_id))
        if provider is None or model is None or not eligible_for_default(kind=kind, provider=provider, model=model):
            return None
        return GetAIBuddyDefaultModelDetail(
            id=default_model.id,
            kind=AIBuddyModelKind(default_model.kind),
            provider_id=default_model.provider_id,
            provider_name=provider.name,
            provider_type=provider.type,
            model_id=default_model.model_id,
            status=default_model.status,
            created_time=default_model.created_time,
            updated_time=default_model.updated_time,
        )


ai_buddy_model_option_service: AIBuddyModelOptionService = AIBuddyModelOptionService()
