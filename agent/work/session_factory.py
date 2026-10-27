import anyio

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.context import ctx
from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.work.generation.handlers import get_generation_handler
from backend.plugin.ai_buddy.agent.work.session import AgentSession
from backend.plugin.ai_buddy.agent.work.types import ChatAgent
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyChatGenerationType,
    AIBuddyModelKind,
    AIBuddyOrigin,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.policy.context import AIBuddyInvocationContext
from backend.plugin.ai_buddy.policy.registry import validate_ai_buddy_invocation
from backend.plugin.ai_buddy.provider.registry import get_provider_adapter
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam, AIBuddyForwardedPropsParam
from backend.plugin.ai_buddy.service.model_service import ai_buddy_model_service
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config
from backend.plugin.ai_buddy.utils.model_catalog import apply_catalog_profile, parse_model_capabilities
from backend.plugin.ai_buddy.utils.thinking_policy import resolve_thinking_policy


async def open_chat_session(
    *,
    db: AsyncSession,
    forwarded_props: AIBuddyForwardedPropsParam,
    user_id: int | None = None,
    conversation_id: str | None = None,
    assistant_id: int | None = None,
    origin: AIBuddyOrigin = AIBuddyOrigin.web,
) -> tuple[AgentSession, ChatAgent]:
    """
    解析供应商与模型，打开会话并构建代理

    :param db: 数据库会话
    :param forwarded_props: 聊天扩展参数
    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :param assistant_id: 新建对话时的助手 ID
    :param origin: 本轮消息来源
    :return:
    """
    provider, model = await ai_buddy_model_service.get_enabled_binding(
        db=db,
        provider_id=forwarded_props.provider_id,
        model_id=forwarded_props.model_id,
        user_id=user_id,
    )
    generation_handler = get_generation_handler(forwarded_props.generation_type)
    generation_handler.validate_provider_type(provider.type)
    try:
        kind = AIBuddyModelKind(model.kind)
    except ValueError as exc:
        raise errors.RequestError(msg='模型类型无效，请重新配置模型') from exc
    generation_handler.validate_model(
        provider_type=provider.type,
        model_name=model.model_id,
        kind=kind,
    )
    if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam):
        forwarded_props = resolve_thinking_policy(
            forwarded_props=forwarded_props,
            capabilities=frozenset(parse_model_capabilities(model.capabilities)),
            policy=model.thinking_policy,
        )

    invocation_context = None
    if user_id is not None:
        invocation_context = AIBuddyInvocationContext(
            provider_id=provider.id,
            provider_type=AIBuddyProviderType(provider.type),
            provider_name=provider.name,
            model_pk=model.id,
            model_id=model.model_id,
            user_id=user_id,
            is_superuser=ctx.is_superuser,
            mcp_ids=tuple(
                forwarded_props.mcp_ids or () if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam) else ()
            ),
            generation_type=forwarded_props.generation_type,
            conversation_id=conversation_id,
            agent_mode=(
                forwarded_props.agent_mode
                if isinstance(forwarded_props, AIBuddyChatForwardedPropsParam)
                else AIBuddyAgentMode.work
            ),
        )
        await validate_ai_buddy_invocation(db=db, context=invocation_context)
    adapter = get_provider_adapter(provider.type)
    adapter.validate_model_id(model.model_id)
    await load_ai_buddy_config(db)
    session = await AgentSession.open(
        adapter=adapter,
        model_name=model.model_id,
        api_key=provider.api_key,
        base_url=provider.api_host,
        for_direct_image=forwarded_props.generation_type == AIBuddyChatGenerationType.image,
    )
    session.invocation_context = invocation_context
    try:
        apply_catalog_profile(
            model=session.model, input_modalities=model.input_modalities, context_window=model.context_window
        )
        agent = await session.build_agent(
            db=db,
            forwarded_props=forwarded_props,
            generation_handler=generation_handler,
            conversation_id=conversation_id,
            assistant_id=assistant_id,
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            catalog_capabilities=frozenset(parse_model_capabilities(model.capabilities)),
            origin=origin,
        )
    except ValueError as exc:
        # 屏蔽取消：任务取消时仍完成客户端关闭，避免连接泄漏
        with anyio.CancelScope(shield=True):
            await session.aclose()
        raise errors.RequestError(msg=f'模型配置无效: {exc}') from exc
    except BaseException:
        with anyio.CancelScope(shield=True):
            await session.aclose()
        raise
    return session, agent
