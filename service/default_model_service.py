from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.work.generation.image import ImageGenerationHandler
from backend.plugin.ai_buddy.crud.crud_default_model import ai_buddy_default_model_dao
from backend.plugin.ai_buddy.crud.crud_model import ai_buddy_model_dao
from backend.plugin.ai_buddy.crud.crud_provider import ai_buddy_provider_dao
from backend.plugin.ai_buddy.enums import AIBuddyModelKind
from backend.plugin.ai_buddy.model import AIBuddyModel, AIBuddyProvider
from backend.plugin.ai_buddy.schema.default_model import GetAIBuddyDefaultModelDetail, UpdateAIBuddyDefaultModelParam
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config
from backend.plugin.ai_buddy.utils.model_catalog import eligible_for_default, require_default_kind
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID


class AIBuddyDefaultModelService:
    """AI 默认模型服务类"""

    async def get_config(
        self,
        *,
        db: AsyncSession,
        kind: AIBuddyModelKind,
        require_enabled: bool = False,
    ) -> GetAIBuddyDefaultModelDetail:
        """
        获取默认模型绑定

        :param db: 数据库会话
        :param kind: 模型类型
        :param require_enabled: 是否要求配置、供应商和模型均已启用
        :return:
        """
        default_model = await ai_buddy_default_model_dao.get_by_kind(db, kind)
        if not default_model:
            raise errors.NotFoundError(msg='默认模型配置不存在')
        if require_enabled and default_model.status != StatusType.enable:
            raise errors.RequestError(msg='默认模型配置已停用')
        provider = await ai_buddy_provider_dao.get(db, default_model.provider_id)
        if not provider:
            raise errors.NotFoundError(msg='默认模型供应商不存在')
        if require_enabled and provider.status != StatusType.enable:
            raise errors.RequestError(msg='默认模型供应商已停用')
        model = await ai_buddy_model_dao.get_by_model_and_provider(
            db, default_model.model_id, default_model.provider_id
        )
        if not model:
            raise errors.NotFoundError(msg='默认模型不存在')
        if require_enabled and model.status != StatusType.enable:
            raise errors.RequestError(msg='默认模型已停用')
        if require_enabled:
            self._validate_kind_binding(kind=kind, provider=provider, model=model)
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

    async def get(self, *, db: AsyncSession, kind: AIBuddyModelKind) -> GetAIBuddyDefaultModelDetail:
        """
        获取已启用的默认模型

        :param db: 数据库会话
        :param kind: 模型类型
        :return:
        """
        return await self.get_config(db=db, kind=kind, require_enabled=True)

    async def update(self, *, db: AsyncSession, kind: AIBuddyModelKind, obj: UpdateAIBuddyDefaultModelParam) -> None:
        """
        更新默认模型

        :param db: 数据库会话
        :param kind: 模型类型
        :param obj: 默认模型配置参数
        :return:
        """
        provider = await ai_buddy_provider_dao.get(db, obj.provider_id)
        if not provider:
            raise errors.NotFoundError(msg='供应商不存在')
        if provider.user_id != SYSTEM_OWNER_USER_ID:
            raise errors.RequestError(msg='默认模型只能绑定平台供应商')
        if provider.status != StatusType.enable:
            raise errors.RequestError(msg='供应商已停用')
        model = await ai_buddy_model_dao.get_by_model_and_provider(db, obj.model_id, obj.provider_id)
        if not model:
            raise errors.NotFoundError(msg='模型不存在')
        if model.status != StatusType.enable:
            raise errors.RequestError(msg='模型已停用')
        self._validate_kind_binding(kind=kind, provider=provider, model=model)
        if kind == AIBuddyModelKind.embedding:
            await load_ai_buddy_config(db, reindex_on_change=False)
        default_model = await ai_buddy_default_model_dao.get_by_kind(db, kind)
        previous_binding = (
            (default_model.provider_id, default_model.model_id, default_model.status) if default_model else None
        )
        if default_model:
            await ai_buddy_default_model_dao.update(db, default_model.id, obj)
        else:
            await ai_buddy_default_model_dao.create(db, kind, obj)
        if (
            kind == AIBuddyModelKind.embedding
            and settings.AI_BUDDY_EMBEDDING_BACKEND == 'remote'
            and obj.status == StatusType.enable
            and previous_binding != (obj.provider_id, obj.model_id, obj.status)
        ):
            from backend.plugin.ai_buddy.service.knowledge_service import ai_buddy_knowledge_service

            ai_buddy_knowledge_service.schedule_reindex(db=db)

    async def get_enabled_or_none(
        self,
        *,
        db: AsyncSession,
        kind: AIBuddyModelKind,
    ) -> GetAIBuddyDefaultModelDetail | None:
        """
        获取已启用的默认模型，未配置时返回空

        :param db: 数据库会话
        :param kind: 模型类型
        :return:
        """
        try:
            return await self.get(db=db, kind=kind)
        except (errors.NotFoundError, errors.RequestError):
            return None

    @staticmethod
    def _validate_kind_binding(*, kind: AIBuddyModelKind, provider: AIBuddyProvider, model: AIBuddyModel) -> None:
        """
        校验默认类型与供应商、模型是否匹配

        :param kind: 模型类型
        :param provider: 供应商
        :param model: 模型
        :return:
        """
        require_default_kind(kind, model)
        if not eligible_for_default(kind=kind, provider=provider, model=model):
            raise errors.RequestError(msg='当前模型或供应商不支持此默认模型用途')
        if kind != AIBuddyModelKind.image:
            return
        handler = ImageGenerationHandler()
        handler.validate_provider_type(provider.type)
        handler.validate_model(
            provider_type=provider.type,
            model_name=model.model_id,
            kind=AIBuddyModelKind(model.kind),
        )


ai_buddy_default_model_service: AIBuddyDefaultModelService = AIBuddyDefaultModelService()
