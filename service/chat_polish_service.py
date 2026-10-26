import asyncio

from pydantic_ai import Agent

from backend.common.context import ctx
from backend.common.exception import errors
from backend.common.log import log
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyChatGenerationType,
    AIBuddyModelKind,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.policy.context import AIBuddyInvocationContext
from backend.plugin.ai_buddy.policy.registry import validate_ai_buddy_invocation
from backend.plugin.ai_buddy.provider.registry import get_provider_adapter
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatPolishParam, GetAIBuddyChatPolishDetail
from backend.plugin.ai_buddy.service.default_model_service import ai_buddy_default_model_service
from backend.plugin.ai_buddy.service.model_service import ai_buddy_model_service
from backend.plugin.ai_buddy.utils.http_client import build_retry_http_client
from backend.plugin.ai_buddy.utils.llm_text import llm_output_text

_POLISH_TIMEOUT_SECONDS = 30.0
_POLISH_SYSTEM_PROMPT = (
    'You are a prompt editor, not an assistant that answers questions.\n'
    'The user message is a DRAFT PROMPT they will later send to another AI. '
    'Your only job is to rewrite that draft so another AI can understand it more '
    'clearly — improve clarity, specificity, structure, and actionable detail.\n'
    'Hard rules:\n'
    '- Do NOT answer the draft, solve the task, or provide the requested content.\n'
    '- Do NOT add explanations, greetings, or meta commentary.\n'
    "- Preserve the user's original intent and language (e.g. keep Chinese if the "
    'draft is Chinese).\n'
    '- Output ONLY the rewritten prompt text — no preamble, labels, quotes, '
    'thinking blocks, or XML tags.'
)


class AIBuddyChatPolishService:
    """输入框草稿润色服务"""

    @staticmethod
    async def polish(
        *,
        user_id: int,
        obj: AIBuddyChatPolishParam,
    ) -> GetAIBuddyChatPolishDetail:
        """
        一次性改写输入框草稿，不写对话历史，不占生成占用标记

        :param user_id: 用户 ID
        :param obj: 润色参数
        :return:
        """
        draft = obj.text.strip()
        if not draft:
            raise errors.RequestError(msg='没有可润色的草稿')
        provider_id = obj.provider_id
        model_id = obj.model_id
        async with async_db_session() as db:
            has_provider = provider_id is not None
            has_model = bool((model_id or '').strip())
            if has_provider != has_model:
                raise errors.RequestError(msg='供应商和模型需要一起传入')
            if has_provider and has_model:
                resolved_provider_id = int(provider_id)
                resolved_model_id = str(model_id).strip()
            else:
                default_model = await ai_buddy_default_model_service.get(db=db, kind=AIBuddyModelKind.chat)
                resolved_provider_id = default_model.provider_id
                resolved_model_id = default_model.model_id
            provider, model = await ai_buddy_model_service.get_enabled_binding(
                db=db, provider_id=resolved_provider_id, model_id=resolved_model_id, user_id=user_id
            )
            if model.kind != AIBuddyModelKind.chat:
                raise errors.RequestError(msg='润色请使用对话模型')
            invocation_context = AIBuddyInvocationContext(
                provider_id=provider.id,
                provider_type=AIBuddyProviderType(provider.type),
                provider_name=provider.name,
                model_pk=model.id,
                model_id=model.model_id,
                user_id=user_id,
                is_superuser=bool(ctx.is_superuser),
                generation_type=AIBuddyChatGenerationType.text,
                agent_mode=AIBuddyAgentMode.work,
            )
            await validate_ai_buddy_invocation(db=db, context=invocation_context)
            provider_type = provider.type
            api_key = provider.api_key
            api_host = provider.api_host
            model_id = model.model_id
        adapter = get_provider_adapter(provider_type)
        adapter.validate_model_id(model_id)
        http_client = build_retry_http_client()
        try:
            llm = adapter.create_model(
                model_name=model_id,
                api_key=api_key,
                base_url=api_host,
                http_client=http_client,
            )
            agent: Agent[None, str] = Agent(llm, instructions=_POLISH_SYSTEM_PROMPT, output_type=str)
            result = await asyncio.wait_for(
                agent.run(f'Rewrite the following draft prompt. Do not answer it.\n\n---\n{draft}\n---'),
                timeout=_POLISH_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            raise errors.RequestError(msg='润色超时，请稍后重试') from None
        except errors.BaseExceptionError:
            raise
        except Exception as exc:
            log.exception(f'润色失败 user_id={user_id} model={model_id}: {exc}')
            raise errors.RequestError(msg='润色失败，请稍后重试') from exc
        finally:
            await http_client.aclose()
        polished = llm_output_text(result)
        if not polished:
            raise errors.RequestError(msg='模型没有返回可写回的草稿')
        return GetAIBuddyChatPolishDetail(text=polished)


ai_buddy_chat_polish_service: AIBuddyChatPolishService = AIBuddyChatPolishService()
