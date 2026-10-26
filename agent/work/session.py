from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, AgentRunResult

from backend.common.log import log
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.work.capability_pipeline import assemble_capabilities
from backend.plugin.ai_buddy.agent.work.generation.image_direct import (
    DirectImageGenerationModel,
    build_direct_image_generation_settings,
)
from backend.plugin.ai_buddy.agent.work.model_settings import build_model_settings
from backend.plugin.ai_buddy.agent.work.persistence import (
    extract_assistant_messages,
    extract_assistant_run_messages,
    persist_completion,
    persist_terminal_completion,
)
from backend.plugin.ai_buddy.agent.work.stream import build_streaming_response
from backend.plugin.ai_buddy.dataclasses import (
    ChatAgentDeps,
    ChatRunContext,
    CompletionPersistenceContext,
    RegenerationPersistenceContext,
)
from backend.plugin.ai_buddy.enums import AIBuddyMessageStatus, AIBuddyModelCapability
from backend.plugin.ai_buddy.schema.image import AIBuddyImageForwardedPropsParam
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config
from backend.plugin.ai_buddy.utils.http_client import build_retry_http_client
from backend.plugin.ai_buddy.utils.run_timeout import resolve_run_timeout

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import httpx2

    from pydantic_ai.images import ImageGenerationModel
    from pydantic_ai.models import Model
    from sqlalchemy.ext.asyncio import AsyncSession
    from starlette.responses import StreamingResponse

    from backend.plugin.ai_buddy.agent.work.generation.base import GenerationHandler
    from backend.plugin.ai_buddy.agent.work.types import ChatAgent, ChatModelMessage
    from backend.plugin.ai_buddy.policy.context import AIBuddyInvocationContext
    from backend.plugin.ai_buddy.provider.base import ProviderAdapter
    from backend.plugin.ai_buddy.schema.chat import AIBuddyForwardedPropsParam


class AgentSession:
    """对话运行时会话，拥有 HTTP/SDK 客户端、模型与 agent 生命周期"""

    def __init__(
        self,
        *,
        adapter: ProviderAdapter,
        model: Model,
        http_client: httpx2.AsyncClient,
        image_generation_model: ImageGenerationModel | None = None,
    ) -> None:
        """保存供应商会话及其客户端资源

        :param adapter: 供应商适配器
        :param model: 模型对象
        :param http_client: HTTP 客户端
        :param image_generation_model: 图片生成模型
        :return:
        """
        self.adapter = adapter
        self.model = model
        self._http_client = http_client
        self._image_generation_model = image_generation_model
        self._closed = False
        self.invocation_context: AIBuddyInvocationContext | None = None

    @classmethod
    async def open(
        cls,
        *,
        adapter: ProviderAdapter,
        model_name: str,
        api_key: str,
        base_url: str,
        for_direct_image: bool = False,
    ) -> AgentSession:
        """
        打开会话并构建模型实例

        :param adapter: 供应商适配器
        :param model_name: 模型名称
        :param api_key: API 密钥
        :param base_url: API 基础地址
        :param for_direct_image: 是否走独立 ImageGenerator
        :return:
        """
        http_client = build_retry_http_client()
        image_generation_model = None
        try:
            if for_direct_image:
                image_generation_model = adapter.create_image_generation_model(
                    model_name=model_name,
                    api_key=api_key,
                    base_url=base_url,
                    http_client=http_client,
                )
                model = DirectImageGenerationModel(image_generation_model)
            else:
                model = adapter.create_model(
                    model_name=model_name,
                    api_key=api_key,
                    base_url=base_url,
                    http_client=http_client,
                )
        except Exception:
            await http_client.aclose()
            raise
        return cls(
            adapter=adapter,
            model=model,
            http_client=http_client,
            image_generation_model=image_generation_model,
        )

    async def aclose(self) -> None:
        """幂等关闭会话及其客户端资源"""
        if self._closed:
            return
        self._closed = True
        close_target = self._image_generation_model if self._image_generation_model is not None else self.model
        try:
            await self.adapter.aclose(close_target)
        finally:
            if not self._http_client.is_closed:
                await self._http_client.aclose()

    async def build_agent(
        self,
        *,
        db: AsyncSession,
        forwarded_props: AIBuddyForwardedPropsParam,
        generation_handler: GenerationHandler,
        conversation_id: str | None = None,
        assistant_id: int | None = None,
        context_window: int | None = None,
        max_output_tokens: int | None = None,
        catalog_capabilities: frozenset[AIBuddyModelCapability] | None = None,
    ) -> ChatAgent:
        """
        构建聊天代理

        :param db: 数据库会话
        :param forwarded_props: 聊天扩展参数
        :param generation_handler: 生成模式处理器
        :param conversation_id: 对话 ID
        :param assistant_id: 新建对话时的助手 ID
        :param context_window: 模型上下文窗口 token 数
        :param max_output_tokens: 模型最大输出 token 上限
        :param catalog_capabilities: 后台配置的模型能力
        :return:
        """
        await load_ai_buddy_config(db)
        if isinstance(self.model, DirectImageGenerationModel) and isinstance(
            forwarded_props, AIBuddyImageForwardedPropsParam
        ):
            self.model.configure(
                settings=build_direct_image_generation_settings(
                    provider_type=self.adapter.provider_type,
                    forwarded_props=forwarded_props,
                )
            )
            return Agent(
                name='fba-image',
                deps_type=ChatAgentDeps,
                model=self.model,
                output_type=generation_handler.get_output_type(),
            )
        profile = self.model.profile
        catalog_capabilities = catalog_capabilities or frozenset()
        supports_tools = (
            bool(profile.get('supports_tools', False)) and AIBuddyModelCapability.tools in catalog_capabilities
        )
        supported_native_tools = profile.get('supported_native_tools', frozenset())
        supports_image_output = bool(profile.get('supports_image_output', False))
        capabilities = await assemble_capabilities(
            db=db,
            adapter=self.adapter,
            forwarded_props=forwarded_props,
            user_id=None if self.invocation_context is None else self.invocation_context.user_id,
            is_superuser=False if self.invocation_context is None else self.invocation_context.is_superuser,
            supports_tools=supports_tools,
            supported_native_tools=supported_native_tools,
            supports_image_output=supports_image_output,
            model=self.model,
            conversation_id=conversation_id,
            assistant_id=assistant_id,
            context_window=context_window,
            catalog_capabilities=catalog_capabilities,
        )
        model_settings = build_model_settings(
            adapter=self.adapter,
            forwarded_props=forwarded_props,
            model_name=self.model.model_name,
            max_output_tokens=max_output_tokens,
        )
        output_type = generation_handler.get_output_type()
        return Agent(
            name='fba-chat',
            deps_type=ChatAgentDeps,
            model=self.model,
            model_settings=model_settings,
            output_type=output_type,
            capabilities=capabilities,
            retries=settings.AI_BUDDY_AGENT_RETRIES,
            tool_timeout=settings.AI_BUDDY_AGENT_TOOL_TIMEOUT_SECONDS,
        )

    async def stream(
        self,
        *,
        user_id: int,
        agent: ChatAgent,
        run_context: ChatRunContext,
        accept: str | None,
        message_history: list[ChatModelMessage],
        persistence: CompletionPersistenceContext | RegenerationPersistenceContext | None = None,
        on_complete: Callable[[AgentRunResult[Any]], Awaitable[None]] | None = None,
        on_run_error: Callable[[str, list[ChatModelMessage], dict[str, Any] | None], Awaitable[None]] | None = None,
        on_interrupted: Callable[[list[ChatModelMessage]], Awaitable[None]] | None = None,
    ) -> StreamingResponse:
        """
        构建 AG-UI 流式响应；on_finish 自动关闭会话

        :param user_id: 用户 ID
        :param agent: 聊天代理
        :param run_context: AG-UI 运行上下文
        :param accept: Accept 请求头
        :param message_history: 消息历史
        :param persistence: 普通聊天持久化上下文
        :param on_complete: 自定义完成回调，未提供时默认调用 persist_completion
        :param on_run_error: 自定义异常回调，未提供时默认持久化错误终态
        :param on_interrupted: 自定义中断回调，未提供时默认持久化中断终态
        :return:
        """
        if on_complete is None or on_run_error is None or on_interrupted is None:
            if not isinstance(persistence, CompletionPersistenceContext):
                raise RuntimeError('缺少聊天生命周期回调')

            async def default_on_complete(result: AgentRunResult[Any]) -> None:
                """保存本轮生成完成后的助手消息

                :param result: 执行结果
                :return:
                """
                async with async_db_session.begin() as db:
                    await persist_completion(
                        db=db,
                        persistence=persistence,
                        messages=extract_assistant_run_messages(result),
                    )

            async def default_on_run_error(
                message: str,
                messages: list[ChatModelMessage],
                detail: dict[str, Any] | None = None,
            ) -> None:
                """将本轮助手消息保存为错误终态

                :param message: 消息内容
                :param messages: 消息列表
                :param detail: 详细信息
                :return:
                """
                await persist_terminal_completion(
                    persistence=persistence,
                    messages=extract_assistant_messages(messages),
                    status=AIBuddyMessageStatus.error,
                    reason=message,
                    detail=detail,
                )

            async def default_on_interrupted(messages: list[ChatModelMessage]) -> None:
                """将本轮助手消息保存为中断终态

                :param messages: 消息列表
                :return:
                """
                await persist_terminal_completion(
                    persistence=persistence,
                    messages=extract_assistant_messages(messages),
                    status=AIBuddyMessageStatus.interrupted,
                )

            on_complete = on_complete or default_on_complete
            on_run_error = on_run_error or default_on_run_error
            on_interrupted = on_interrupted or default_on_interrupted

        async def on_finish() -> None:
            """关闭供应商会话并记录清理失败"""
            try:
                await self.aclose()
            except Exception as exc:
                log.warning(f'关闭模型供应商客户端失败: {exc}')

        return await build_streaming_response(
            user_id=user_id,
            agent=agent,
            run_input=run_context.run_input,
            accept=accept,
            message_history=message_history,
            on_complete=on_complete,
            on_run_error=on_run_error,
            on_interrupted=on_interrupted,
            on_finish=on_finish,
            conversation_id=run_context.conversation_id,
            run_timeout=resolve_run_timeout(getattr(run_context.forwarded_props, 'run_timeout', None)),
        )
