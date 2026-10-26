from collections.abc import Sequence
from time import perf_counter
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.common.log import log
from backend.common.pagination import paging_data
from backend.plugin.ai_buddy.crud.crud_default_model import ai_buddy_default_model_dao
from backend.plugin.ai_buddy.crud.crud_model import ai_buddy_model_dao
from backend.plugin.ai_buddy.crud.crud_provider import ai_buddy_provider_dao
from backend.plugin.ai_buddy.enums import (
    MODEL_INPUT_MODALITIES,
    AIBuddyModelCapability,
    AIBuddyModelKind,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.model import AIBuddyModel, AIBuddyProvider
from backend.plugin.ai_buddy.schema.model import (
    CreateAIBuddyModelParam,
    CreateAIBuddyModelsParam,
    CreateMyAIBuddyModelParam,
    DeleteAIBuddyModelParam,
    GetMyAIBuddyModelDetail,
    UpdateAIBuddyModelParam,
    UpdateMyAIBuddyModelParam,
)
from backend.plugin.ai_buddy.schema.model_architecture import (
    GetAIBuddyModelArchitectureSyncDetail,
    GetAIBuddyModelArchitectureSyncSkippedDetail,
)
from backend.plugin.ai_buddy.service.model_architecture_service import (
    ai_buddy_model_architecture_service,
)
from backend.plugin.ai_buddy.service.provider_service import ai_buddy_provider_service
from backend.plugin.ai_buddy.utils.model_catalog import (
    normalize_capabilities,
    normalize_model_param,
    parse_model_capabilities,
    validate_model_binding,
)
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID


class AIBuddyModelService:
    """AI 模型服务类"""

    @staticmethod
    async def get_enabled_binding(
        *, db: AsyncSession, provider_id: int, model_id: str, user_id: int | None
    ) -> tuple[AIBuddyProvider, AIBuddyModel]:
        """
        获取当前调用可见且已启用的供应商和模型

        :param db: 数据库会话
        :param provider_id: 供应商 ID
        :param model_id: 模型标识
        :param user_id: 用户 ID，内部调用可为空
        :return:
        """
        provider = (
            await ai_buddy_provider_dao.get(db, provider_id)
            if user_id is None
            else await ai_buddy_provider_dao.get_visible(db, provider_id, user_id)
        )
        if not provider:
            raise errors.NotFoundError(msg='供应商不存在')
        if provider.status != StatusType.enable:
            raise errors.RequestError(msg='此供应商暂不可用，请更换供应商或联系系统管理员')
        model = await ai_buddy_model_dao.get_by_model_and_provider(db, model_id, provider_id)
        if not model:
            raise errors.NotFoundError(msg='供应商模型不存在')
        if model.status != StatusType.enable:
            raise errors.RequestError(msg='此模型暂不可用，请更换模型或联系系统管理员')
        return provider, model

    @staticmethod
    async def get_all(
        *,
        db: AsyncSession,
        provider_id: int,
        kind: AIBuddyModelKind | None = None,
        capability: AIBuddyModelCapability | None = None,
    ) -> Sequence[AIBuddyModel]:
        """
        获取所有 AI 模型

        :param db: 数据库会话
        :param provider_id: 供应商 ID
        :param kind: 模型类型
        :param capability: 模型能力
        :return:
        """
        return await ai_buddy_model_dao.get_all(
            db,
            provider_id=provider_id,
            status=StatusType.enable.value,
            kind=None if kind is None else kind.value,
            capability=None if capability is None else capability.value,
        )

    @staticmethod
    async def get(*, db: AsyncSession, pk: int) -> AIBuddyModel:
        """
        获取 AI 模型

        :param db: 数据库会话
        :param pk: 模型 ID
        :return:
        """
        ai_buddy_model = await ai_buddy_model_dao.get(db, pk)
        if not ai_buddy_model:
            raise errors.NotFoundError(msg='模型不存在')
        return ai_buddy_model

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        provider_id: int | None,
        model_id: str | None,
        status: int | None,
        kind: AIBuddyModelKind | None = None,
        capability: AIBuddyModelCapability | None = None,
    ) -> dict[str, Any]:
        """
        获取 AI 模型列表

        :param db: 数据库会话
        :param provider_id: 供应商 ID
        :param model_id: 模型 ID
        :param status: 状态
        :param kind: 模型类型
        :param capability: 模型能力
        :return:
        """
        ai_buddy_model_select = await ai_buddy_model_dao.get_select(
            provider_id,
            model_id,
            status,
            None if kind is None else kind.value,
            None if capability is None else capability.value,
        )
        return await paging_data(db, ai_buddy_model_select)

    @staticmethod
    def _require_system_provider(*, provider: AIBuddyProvider) -> None:
        """
        平台模型只能挂在内置供应商上

        :param provider: 供应商
        :return:
        """
        if provider.user_id != SYSTEM_OWNER_USER_ID:
            raise errors.ForbiddenError(msg='不能为用户自建供应商添加平台模型')

    @staticmethod
    async def _create_for_provider(
        *,
        db: AsyncSession,
        obj: CreateAIBuddyModelParam,
        provider: AIBuddyProvider,
    ) -> AIBuddyModel:
        """
        在指定供应商下创建模型

        :param db: 数据库会话
        :param obj: 创建模型参数
        :param provider: 供应商
        :return:
        """
        obj = normalize_model_param(obj)
        validate_model_binding(kind=obj.kind, provider_type=provider.type)
        if provider.type == AIBuddyProviderType.openrouter and '/' not in obj.model_id:
            raise errors.RequestError(msg='OpenRouter 模型 ID 必须包含供应商前缀，例如 openai/gpt-4o-mini')
        existed = await ai_buddy_model_dao.get_by_model_and_provider(db, obj.model_id, obj.provider_id)
        if existed:
            raise errors.ConflictError(msg='模型已存在')
        return await ai_buddy_model_dao.create(db, obj)

    async def create(self, *, db: AsyncSession, obj: CreateAIBuddyModelParam) -> None:
        """
        创建平台模型

        :param db: 数据库会话
        :param obj: 创建模型参数
        :return:
        """
        provider = await ai_buddy_provider_dao.get(db, obj.provider_id)
        if not provider:
            raise errors.NotFoundError(msg='供应商不存在')
        self._require_system_provider(provider=provider)
        await self._create_for_provider(db=db, obj=obj, provider=provider)

    async def bulk_create(self, *, db: AsyncSession, obj: CreateAIBuddyModelsParam) -> None:
        """
        批量创建平台模型

        :param db: 数据库会话
        :param obj: 批量创建模型参数
        :return:
        """
        pairs: list[tuple[int, str]] = []
        pair_set: set[tuple[int, str]] = set()
        items = [normalize_model_param(item) for item in obj.items]
        provider_ids = list({item.provider_id for item in items})
        providers = await ai_buddy_provider_dao.get_by_ids(db, provider_ids)
        providers_by_id = {provider.id: provider for provider in providers}
        if len(providers_by_id) != len(provider_ids):
            raise errors.NotFoundError(msg='供应商不存在')
        for provider in providers:
            self._require_system_provider(provider=provider)
        for item in items:
            pair = (item.provider_id, item.model_id)
            if pair in pair_set:
                raise errors.RequestError(msg='本次请求中存在重复模型，请检查后重试')
            provider = providers_by_id[item.provider_id]
            validate_model_binding(kind=item.kind, provider_type=provider.type)
            if provider.type == AIBuddyProviderType.openrouter and '/' not in item.model_id:
                raise errors.RequestError(msg='OpenRouter 模型 ID 必须包含供应商前缀，例如 openai/gpt-4o-mini')
            pair_set.add(pair)
            pairs.append(pair)
        existed_models = await ai_buddy_model_dao.get_by_provider_model_pairs(db, pairs)
        if existed_models:
            raise errors.ConflictError(msg='存在已添加的模型，请勿重复创建')
        await ai_buddy_model_dao.bulk_create(db, [item.model_dump(mode='json') for item in items])

    async def update(self, *, db: AsyncSession, pk: int, obj: UpdateAIBuddyModelParam) -> int:
        """
        更新平台模型

        :param db: 数据库会话
        :param pk: 模型 ID
        :param obj: 更新模型参数
        :return:
        """
        obj = normalize_model_param(obj)
        ai_buddy_model = await ai_buddy_model_dao.get(db, pk)
        if not ai_buddy_model:
            raise errors.NotFoundError(msg='模型不存在')
        current_provider = await ai_buddy_provider_dao.get(db, ai_buddy_model.provider_id)
        if current_provider is None:
            raise errors.NotFoundError(msg='供应商不存在')
        self._require_system_provider(provider=current_provider)
        provider = await ai_buddy_provider_dao.get(db, obj.provider_id)
        if not provider:
            raise errors.NotFoundError(msg='供应商不存在')
        self._require_system_provider(provider=provider)
        validate_model_binding(kind=obj.kind, provider_type=provider.type)
        if provider.type == AIBuddyProviderType.openrouter and '/' not in obj.model_id:
            raise errors.RequestError(msg='OpenRouter 模型 ID 必须包含供应商前缀，例如 openai/gpt-4o-mini')
        existed_model = await ai_buddy_model_dao.get_by_model_and_provider(db, obj.model_id, obj.provider_id)
        if existed_model and existed_model.id != pk:
            raise errors.ConflictError(msg='模型已存在')
        if 'thinking_policy' not in obj.model_fields_set:
            obj = UpdateAIBuddyModelParam.model_validate({
                **obj.model_dump(),
                'thinking_policy': ai_buddy_model.thinking_policy,
            })
        return await ai_buddy_model_dao.update(db, pk, obj)

    async def sync_backend_architecture(self, *, db: AsyncSession) -> GetAIBuddyModelArchitectureSyncDetail:
        """
        从 models.dev 同步所有后台模型的架构配置

        :param db: 数据库会话
        :return:
        """
        return await self._sync_architecture(db=db, owner_id=SYSTEM_OWNER_USER_ID)

    async def sync_user_architecture(self, *, db: AsyncSession, user_id: int) -> GetAIBuddyModelArchitectureSyncDetail:
        """
        从 models.dev 同步当前用户模型的架构配置

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        return await self._sync_architecture(db=db, owner_id=user_id)

    @staticmethod
    async def _sync_architecture(*, db: AsyncSession, owner_id: int) -> GetAIBuddyModelArchitectureSyncDetail:  # ruff:ignore[complex-structure]
        """
        按模型归属同步架构配置

        :param db: 数据库会话
        :param owner_id: 模型归属用户 ID
        :return:
        """
        started = perf_counter()
        providers = await ai_buddy_provider_dao.get_all_owned(db, owner_id)
        providers_by_id = {provider.id: provider for provider in providers}
        models = await ai_buddy_model_dao.get_all_by_providers(db, list(providers_by_id))
        result = GetAIBuddyModelArchitectureSyncDetail(updated_count=0, skipped=[])
        if not models:
            return result
        queried = perf_counter()
        catalog = await ai_buddy_model_architecture_service.fetch_catalog()
        fetched = perf_counter()

        for model in models:
            provider = providers_by_id[model.provider_id]
            try:
                current_kind = AIBuddyModelKind(model.kind)
                suggestion = ai_buddy_model_architecture_service.get_suggestion(
                    catalog=catalog,
                    provider_type=AIBuddyProviderType(provider.type),
                    model_id=model.model_id,
                    current_kind=current_kind,
                )
                if not suggestion.model_dump(exclude={'source', 'last_updated'}, exclude_none=True):
                    raise errors.RequestError(msg='models.dev 未提供可应用的模型架构信息')
                kind = suggestion.kind or current_kind
                capabilities = parse_model_capabilities(model.capabilities)
                thinking_policy = model.thinking_policy
                if kind == AIBuddyModelKind.chat:
                    for capability, supported in (
                        (AIBuddyModelCapability.tools, suggestion.tools),
                        (AIBuddyModelCapability.thinking, suggestion.thinking),
                    ):
                        if supported is True and capability not in capabilities:
                            capabilities.append(capability)
                        elif supported is False and capability in capabilities:
                            capabilities.remove(capability)
                    if suggestion.thinking_policy is not None:
                        thinking_policy = suggestion.thinking_policy.model_dump(mode='json')
                        current_policy = model.thinking_policy
                        current_default = (
                            current_policy.get('default_level') if isinstance(current_policy, dict) else None
                        )
                        if current_default in thinking_policy['levels']:
                            thinking_policy['default_level'] = current_default
                    if AIBuddyModelCapability.thinking not in capabilities:
                        thinking_policy = None
                    capabilities = normalize_capabilities(capabilities)
                else:
                    capabilities = []
                    thinking_policy = None
                input_modalities = (
                    model.input_modalities if suggestion.input_modalities is None else suggestion.input_modalities
                )
                if kind != current_kind and input_modalities is not None:
                    input_modalities = [item for item in input_modalities if item in MODEL_INPUT_MODALITIES[kind]]
                obj = UpdateAIBuddyModelParam(
                    provider_id=model.provider_id,
                    model_id=model.model_id,
                    kind=kind,
                    capabilities=capabilities,
                    input_modalities=input_modalities,
                    thinking_policy=thinking_policy,
                    context_window=(
                        model.context_window if suggestion.context_window is None else suggestion.context_window
                    ),
                    max_output_tokens=(
                        model.max_output_tokens
                        if suggestion.max_output_tokens is None
                        else suggestion.max_output_tokens
                    ),
                    status=model.status,
                )
                validate_model_binding(kind=obj.kind, provider_type=provider.type)
            except (errors.NotFoundError, errors.RequestError, ValidationError) as exc:
                reason = exc.errors()[0]['msg'] if isinstance(exc, ValidationError) else exc.msg
                result.skipped.append(
                    GetAIBuddyModelArchitectureSyncSkippedDetail(id=model.id, model_id=model.model_id, reason=reason)
                )
                continue
            result.updated_count += await ai_buddy_model_dao.update_architecture(db, model.id, obj)

        finished = perf_counter()
        log.info(
            f'AI 模型架构同步耗时: owner={owner_id} query={(queried - started) * 1000:.2f}ms '
            f'catalog={(fetched - queried) * 1000:.2f}ms apply={(finished - fetched) * 1000:.2f}ms '
            f'models={len(models)} updated={result.updated_count} skipped={len(result.skipped)}'
        )
        return result

    @staticmethod
    async def delete(*, db: AsyncSession, obj: DeleteAIBuddyModelParam) -> int:
        """
        删除平台模型

        :param db: 数据库会话
        :param obj: 模型 ID 列表
        :return:
        """
        ai_buddy_models = await ai_buddy_model_dao.get_by_ids(db, obj.pks)
        provider_ids = list({model.provider_id for model in ai_buddy_models})
        providers = await ai_buddy_provider_dao.get_by_ids(db, provider_ids)
        if any(provider.user_id != SYSTEM_OWNER_USER_ID for provider in providers):
            raise errors.ForbiddenError(msg='用户自建模型请在客户端删除')
        await ai_buddy_default_model_dao.delete_by_provider_model_pairs(
            db,
            [(ai_buddy_model.provider_id, ai_buddy_model.model_id) for ai_buddy_model in ai_buddy_models],
        )
        return await ai_buddy_model_dao.delete(db, obj.pks)

    async def get_mine(self, *, db: AsyncSession, pk: int, user_id: int) -> GetMyAIBuddyModelDetail:
        """
        获取当前用户自己的模型

        :param db: 数据库会话
        :param pk: 模型 ID
        :param user_id: 用户 ID
        :return:
        """
        model, provider = await self._get_owned_model(db=db, pk=pk, user_id=user_id)
        return self._to_my_detail(model=model, provider=provider)

    async def get_mine_all(self, *, db: AsyncSession, user_id: int) -> list[GetMyAIBuddyModelDetail]:
        """
        获取当前用户自己的全部模型

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        providers = await ai_buddy_provider_dao.get_all_owned(db, user_id)
        provider_by_id = {provider.id: provider for provider in providers}
        models = await ai_buddy_model_dao.get_all_by_providers(db, list(provider_by_id))
        return [self._to_my_detail(model=model, provider=provider_by_id[model.provider_id]) for model in models]

    async def create_mine(self, *, db: AsyncSession, obj: CreateMyAIBuddyModelParam, user_id: int) -> None:
        """
        在用户自己的供应商下创建模型

        :param db: 数据库会话
        :param obj: 创建参数
        :param user_id: 用户 ID
        :return:
        """
        provider = await ai_buddy_provider_service.get_mine(
            db=db,
            pk=obj.provider_id,
            user_id=user_id,
        )
        await self._create_for_provider(
            db=db,
            obj=CreateAIBuddyModelParam(
                provider_id=provider.id,
                model_id=obj.model_id,
                name=obj.name,
                kind=obj.kind,
                capabilities=obj.capabilities,
                input_modalities=obj.input_modalities,
                thinking_policy=obj.thinking_policy,
                context_window=obj.context_window,
                max_output_tokens=obj.max_output_tokens,
                sort=obj.sort,
                status=obj.status,
                remark=obj.remark,
            ),
            provider=provider,
        )

    async def update_mine(self, *, db: AsyncSession, pk: int, obj: UpdateMyAIBuddyModelParam, user_id: int) -> int:
        """
        更新当前用户自己的模型

        :param db: 数据库会话
        :param pk: 模型 ID
        :param obj: 更新参数
        :param user_id: 用户 ID
        :return:
        """
        model, _ = await self._get_owned_model(db=db, pk=pk, user_id=user_id)
        next_provider = await ai_buddy_provider_service.get_mine(
            db=db,
            pk=obj.provider_id,
            user_id=user_id,
        )
        payload = normalize_model_param(
            UpdateAIBuddyModelParam(
                provider_id=next_provider.id,
                model_id=obj.model_id,
                name=obj.name,
                kind=obj.kind,
                capabilities=obj.capabilities,
                input_modalities=obj.input_modalities,
                thinking_policy=(
                    obj.thinking_policy if 'thinking_policy' in obj.model_fields_set else model.thinking_policy
                ),
                context_window=obj.context_window,
                max_output_tokens=obj.max_output_tokens,
                sort=obj.sort,
                status=obj.status,
                remark=obj.remark,
            )
        )
        validate_model_binding(kind=payload.kind, provider_type=next_provider.type)
        if next_provider.type == AIBuddyProviderType.openrouter and '/' not in payload.model_id:
            raise errors.RequestError(msg='OpenRouter 模型 ID 必须包含供应商前缀，例如 openai/gpt-4o-mini')
        existed = await ai_buddy_model_dao.get_by_model_and_provider(db, payload.model_id, next_provider.id)
        if existed and existed.id != pk:
            raise errors.ConflictError(msg='模型已存在')
        return await ai_buddy_model_dao.update(db, pk, payload)

    async def delete_mine(self, *, db: AsyncSession, pk: int, user_id: int) -> int:
        """
        删除当前用户自己的模型

        :param db: 数据库会话
        :param pk: 模型 ID
        :param user_id: 用户 ID
        :return:
        """
        await self._get_owned_model(db=db, pk=pk, user_id=user_id)
        return await ai_buddy_model_dao.delete(db, [pk])

    @staticmethod
    async def _get_owned_model(
        *,
        db: AsyncSession,
        pk: int,
        user_id: int,
    ) -> tuple[AIBuddyModel, AIBuddyProvider]:
        """
        获取当前用户自己的模型及其供应商

        :param db: 数据库会话
        :param pk: 模型 ID
        :param user_id: 用户 ID
        :return:
        """
        model = await ai_buddy_model_dao.get(db, pk)
        if model is None:
            raise errors.NotFoundError(msg='模型不存在')
        provider = await ai_buddy_provider_dao.get(db, model.provider_id)
        if provider is None or provider.user_id != user_id:
            raise errors.NotFoundError(msg='模型不存在')
        return model, provider

    @staticmethod
    def _to_my_detail(*, model: AIBuddyModel, provider: AIBuddyProvider) -> GetMyAIBuddyModelDetail:
        """
        组装客户端模型详情

        :param model: 模型
        :param provider: 供应商
        :return:
        """
        return GetMyAIBuddyModelDetail(
            id=model.id,
            provider_id=model.provider_id,
            model_id=model.model_id,
            name=model.name,
            kind=AIBuddyModelKind(model.kind),
            capabilities=parse_model_capabilities(model.capabilities),
            input_modalities=model.input_modalities,
            thinking_policy=model.thinking_policy,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            sort=model.sort,
            status=StatusType(model.status),
            remark=model.remark,
            created_time=model.created_time,
            updated_time=model.updated_time,
            type=AIBuddyProviderType(provider.type),
            api_key=provider.api_key,
            api_host=provider.api_host,
            user_id=provider.user_id,
        )


ai_buddy_model_service: AIBuddyModelService = AIBuddyModelService()
