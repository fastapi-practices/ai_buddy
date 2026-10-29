from pydantic_ai.models import Model

from backend.common.exception import errors
from backend.plugin.ai_buddy.dataclasses import CapabilityContext
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType, AIBuddyModelKind, AIBuddyProviderType
from backend.plugin.ai_buddy.policy.context import AIBuddyInvocationContext
from backend.plugin.ai_buddy.policy.registry import validate_ai_buddy_invocation
from backend.plugin.ai_buddy.service.model_service import ai_buddy_model_service
from backend.plugin.ai_buddy.utils.model_catalog import apply_catalog_profile


def auxiliary_model_name(ctx: CapabilityContext, value: str) -> str:
    """
    接受本轮供应商下的模型名，拒绝跨供应商隐式环境凭据

    :param ctx: 运行上下文
    :param value: 待处理值
    :return:
    """
    prefix, separator, name = value.partition(':')
    if not separator or '/' in prefix:
        return value
    allowed = {ctx.adapter.provider_type.name, ctx.adapter.provider_type.name.replace('_', '-')}
    if ctx.model is not None:
        allowed.add(ctx.model.system)
    if prefix not in allowed or not name:
        raise errors.RequestError(msg='辅助模型必须属于当前供应商，请在当前供应商中配置模型')
    return name


async def bind_auxiliary_model(ctx: CapabilityContext, name: str) -> Model:
    """
    校验模型归属与调用策略，并复用本轮供应商和客户端

    :param ctx: 运行上下文
    :param name: 模型名称
    :return:
    """
    provider, model = await ai_buddy_model_service.get_enabled_binding(
        db=ctx.db, provider_id=ctx.forwarded_props.provider_id, model_id=name, user_id=ctx.user_id
    )
    if model.kind != AIBuddyModelKind.chat:
        raise errors.RequestError(msg='辅助模型必须为对话模型')
    ctx.adapter.validate_model_id(model.model_id)
    if ctx.user_id is not None:
        await validate_ai_buddy_invocation(
            db=ctx.db,
            context=AIBuddyInvocationContext(
                provider_id=provider.id,
                provider_type=AIBuddyProviderType(provider.type),
                provider_name=provider.name,
                model_pk=model.id,
                model_id=model.model_id,
                user_id=ctx.user_id,
                is_superuser=ctx.is_superuser,
                generation_type=AIBuddyChatGenerationType.text,
                conversation_id=ctx.conversation_id,
            ),
        )
    if ctx.model is None:
        raise errors.RequestError(msg='当前会话缺少辅助模型所需的供应商配置')
    if name == ctx.model.model_name:
        return ctx.model
    if ctx.model.provider is None:
        raise errors.RequestError(msg='当前供应商不支持共享辅助模型客户端')
    # 公开 provider 对象持有已配置的凭据和连接，由主会话统一关闭
    bound = type(ctx.model)(name, provider=ctx.model.provider)
    apply_catalog_profile(model=bound, input_modalities=model.input_modalities, context_window=model.context_window)
    return bound
