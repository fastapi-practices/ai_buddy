from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING, Any

import anyio

from opensandbox.exceptions import SandboxException
from pydantic_ai import (
    Agent,
    CapabilityEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    InstructionPart,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    Tool,
    capture_run_messages,
)
from pydantic_ai.capabilities import Caching, Thinking
from pydantic_ai.messages import (
    TextPart,
    TextPartDelta,
    ThinkingPart,
    ThinkingPartDelta,
    repair_messages,
)
from pydantic_ai.workspaces import WorkspaceError
from pydantic_ai_harness.repair_tool_arguments import RepairToolArguments
from pydantic_core import SchemaValidator, core_schema

from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.coding.attachments import coding_user_content
from backend.plugin.ai_buddy.agent.coding.prompts import build_agent_system_prompt
from backend.plugin.ai_buddy.agent.coding.protocol.acp.models import build_acp_config
from backend.plugin.ai_buddy.agent.coding.protocol.acp.service import ACPService
from backend.plugin.ai_buddy.agent.coding.protocol.acp.tool import build_acp_runner_tool
from backend.plugin.ai_buddy.agent.coding.protocol.pydantic_ai.capabilities import build_coding_capabilities
from backend.plugin.ai_buddy.agent.coding.protocol.pydantic_ai.context import compact_coding_history
from backend.plugin.ai_buddy.agent.coding.types import AgentMessage, AgentToolCall, AgentUsage
from backend.plugin.ai_buddy.agent.coding.workspace import CodingWorkspace
from backend.plugin.ai_buddy.agent.work.ag_ui import BuddyAGUIEventStream
from backend.plugin.ai_buddy.agent.work.model_settings import build_model_settings
from backend.plugin.ai_buddy.dataclasses import ChatAgentDeps
from backend.plugin.ai_buddy.enums import (
    AIBuddyMessageRole,
    AIBuddyMessageStatus,
    AIBuddyPermissionMode,
    AIBuddyToolPolicy,
)
from backend.plugin.ai_buddy.provider.registry import get_provider_adapter
from backend.plugin.ai_buddy.security.jev import build_jev_capabilities
from backend.plugin.ai_buddy.security.tool_policy import resolve_tool_policy
from backend.plugin.ai_buddy.security.tool_schema import build_tool_args_validator
from backend.plugin.ai_buddy.utils.citation import text_part_citations
from backend.plugin.ai_buddy.utils.http_client import build_retry_http_client
from backend.plugin.ai_buddy.utils.model_catalog import apply_catalog_profile
from backend.plugin.ai_buddy.utils.run_timeout import resolve_run_timeout

if TYPE_CHECKING:
    from collections.abc import AsyncIterable

    from pydantic_ai import AgentStreamEvent, RunContext

    from backend.plugin.ai_buddy.agent.coding.protocol.base import (
        CancelledCheck,
        CodingHostSpec,
        EmitEvent,
        PersistMessage,
        WaitApproval,
    )
    from backend.plugin.ai_buddy.agent.coding.tools import BoundAgentTool
    from backend.plugin.ai_buddy.agent.coding.types import AgentRunContext


class PydanticAICodingSession:
    """用 Pydantic AI 跑编码循环的宿主会话"""

    def __init__(self, *, spec: CodingHostSpec, tools: list[BoundAgentTool]) -> None:
        """
        绑定编码工具与宿主会话配置

        :param spec: 宿主规格
        :param tools: 工具列表
        :return:
        """
        self.run_context: AgentRunContext = spec.run_context
        self._spec = spec
        self._tools = list(tools)
        self.ui_waiters: dict[str, asyncio.Future[bool]] = {}
        self._closed = False
        self._acp_service: ACPService | None = None
        if spec.run_context.acp_runner_enabled:
            acp_config = build_acp_config(
                runner=spec.run_context.acp_runner_name,
            )
            self._acp_service = ACPService(
                config=acp_config,
                bridge_id=spec.run_context.acp_bridge_id,
                user_id=spec.run_context.user_id,
                cwd=spec.run_context.acp_cwd,
                permission_mode=spec.run_context.permission_mode,
                input_attachments=spec.run_context.input_attachments,
                imported_attachment_hashes=frozenset(
                    spec.forwarded_props.acp_imported_attachment_hashes if spec.forwarded_props else ()
                ),
            )
            self._tools.append(
                build_acp_runner_tool(
                    service=self._acp_service,
                    config=acp_config,
                    thread_id=spec.run_context.conversation_id,
                )
            )

    def resolve_ui(self, request_id: str, *, approved: bool) -> bool:
        """
        兑现宿主 UI 确认

        :param request_id: 请求 ID
        :param approved: 是否批准
        :return:
        """
        future = self.ui_waiters.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(approved)
        return True

    async def wait_ui(self, request_id: str) -> bool:
        """
        等待审批结果

        :param request_id: 请求 ID
        :return:
        """
        future = self.ui_waiters.get(request_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self.ui_waiters[request_id] = future
        return await future

    async def run(  # ruff: ignore[complex-structure]
        self,
        *,
        prompt: str,
        emit: EmitEvent,
        persist_message: PersistMessage,
        is_cancelled: CancelledCheck,
        wait_approval: WaitApproval | None = None,
    ) -> tuple[AIBuddyMessageStatus, AgentUsage]:
        """
        执行本轮提示

        :param prompt: 用户提示
        :param emit: 事件回调
        :param persist_message: 消息落库
        :param is_cancelled: 取消检查
        :param wait_approval: 审批等待
        :return:
        """
        active_acp_call: str | None = None
        acp_text = ''
        if self._acp_service is not None:
            self._acp_service.set_wait_approval(wait_approval)

            async def acp_event(payload: dict[str, Any], _is_last: object) -> None:
                """
                将 ACP 执行进度转换为编码运行事件

                :param payload: 事件载荷
                :param _is_last: 是否为末尾事件
                :return:
                """
                nonlocal acp_text
                event_type = payload.get('type')
                if event_type == 'text' and payload.get('is_chunk'):
                    acp_text += payload['text']
                    if active_acp_call:
                        await emit('tool_result', {'call_id': active_acp_call, 'result': acp_text})
                elif event_type == 'thinking':
                    await emit('thinking', {'delta': payload['text']})
                elif event_type in {'tool_start', 'tool_update'}:
                    call_id = f'acp:{payload["call_id"]}'
                    await emit(
                        'tool_start',
                        {
                            'call_id': call_id,
                            'name': payload['name'],
                            'arguments': payload.get('raw_input') or {},
                        },
                    )
                    if payload.get('status') in {'completed', 'failed'}:
                        await emit(
                            'tool_result',
                            {
                                'call_id': call_id,
                                'result': str(payload.get('raw_output') or payload.get('detail') or ''),
                            },
                        )

            self._acp_service.set_event_handler(acp_event)
        await persist_message(AgentMessage(role=AIBuddyMessageRole.user, content=prompt))
        adapter = get_provider_adapter(self._spec.provider_type)
        http_client = build_retry_http_client()
        model = None
        try:
            model = adapter.create_model(
                model_name=self._spec.model_id,
                api_key=self._spec.api_key,
                base_url=self._spec.api_host,
                http_client=http_client,
            )
            apply_catalog_profile(
                model=model, input_modalities=self._spec.input_modalities, context_window=self._spec.context_window
            )
            resource_capabilities = await build_coding_capabilities(
                spec=self._spec,
                model=model,
                adapter=adapter,
                bound_tool_names=frozenset(item.spec.name for item in self._tools),
                wait_approval=wait_approval,
            )
            agent: Agent[ChatAgentDeps, str] = Agent(
                model,
                name='buddy_coding',
                deps_type=ChatAgentDeps,
                instructions=InstructionPart(build_agent_system_prompt(self.run_context), on_change='append'),
                tools=[
                    _bound_tool(
                        item,
                        permission_mode=self.run_context.permission_mode,
                        wait_approval=wait_approval,
                        tool_policies=self.run_context.tool_policies,
                        mcp_approve_writes=self.run_context.mcp_approve_writes,
                    )
                    for item in self._tools
                ],
                output_type=str,
                model_settings=(
                    build_model_settings(
                        adapter=adapter,
                        forwarded_props=self._spec.forwarded_props,
                        model_name=self._spec.model_id,
                    )
                    if self._spec.forwarded_props is not None
                    else None
                ),
                capabilities=[
                    Caching(self._spec.forwarded_props.cache_enabled if self._spec.forwarded_props else True),
                    *(
                        []
                        if self._spec.thinking is None
                        else [Thinking(False if self._spec.thinking == 'off' else self._spec.thinking)]
                    ),
                    RepairToolArguments(),
                    *build_jev_capabilities(allow_ask=False),
                    *resource_capabilities,
                ],
                retries=settings.AI_BUDDY_AGENT_RETRIES,
                tool_timeout=settings.AI_BUDDY_AGENT_TOOL_TIMEOUT_SECONDS,
            )
            if await is_cancelled():
                return AIBuddyMessageStatus.interrupted, AgentUsage()
            ui_stream = BuddyAGUIEventStream(
                thread_id=self.run_context.conversation_id,
                run_id=self.run_context.run_id,
            )

            async def events(  # ruff: ignore[complex-structure]
                _ctx: RunContext[ChatAgentDeps], stream: AsyncIterable[AgentStreamEvent]
            ) -> None:
                """
                将模型原生事件转发为编码运行事件

                :param _ctx: 运行上下文
                :param stream: 事件流
                :return:
                """
                nonlocal active_acp_call, acp_text
                async for event in stream:
                    if isinstance(event, CapabilityEvent):
                        async for ui_event in ui_stream.handle_capability_event(event):
                            await emit('ag_ui', ui_event.model_dump(mode='json', by_alias=True, exclude_none=True))
                    elif isinstance(event, PartStartEvent):
                        if isinstance(event.part, TextPart) and event.part.content:
                            await emit('text', {'delta': event.part.content})
                        elif isinstance(event.part, ThinkingPart) and event.part.content:
                            await emit('thinking', {'delta': event.part.content})
                    elif isinstance(event, PartDeltaEvent):
                        if isinstance(event.delta, TextPartDelta):
                            await emit('text', {'delta': event.delta.content_delta})
                        elif isinstance(event.delta, ThinkingPartDelta) and event.delta.content_delta:
                            await emit('thinking', {'delta': event.delta.content_delta})
                    elif isinstance(event, PartEndEvent) and isinstance(event.part, TextPart):
                        sources = text_part_citations([event.part])
                        if sources:
                            await emit('citations', {'sources': [source.model_dump() for source in sources]})
                    elif isinstance(event, FunctionToolCallEvent):
                        if event.part.tool_name == 'acp_runner':
                            active_acp_call = event.part.tool_call_id
                            acp_text = ''
                        await emit(
                            'tool_start',
                            {
                                'call_id': event.part.tool_call_id,
                                'name': event.part.tool_name,
                                'arguments': event.part.args_as_dict(),
                            },
                        )
                    elif isinstance(event, FunctionToolResultEvent):
                        async for ui_event in ui_stream.handle_function_tool_result(event):
                            await emit('ag_ui', ui_event.model_dump(mode='json', by_alias=True, exclude_none=True))

            history = await compact_coding_history(
                self._spec.message_history,
                enabled=False,
                keep_messages=self._spec.compaction_keep_messages,
                max_messages=self._spec.compaction_max_messages,
            )
            with capture_run_messages() as captured:
                try:
                    result = await agent.run(
                        coding_user_content(self._spec.user_content, can_import=self.run_context.sandbox is not None)
                        or prompt,
                        deps=ChatAgentDeps(
                            user_id=self.run_context.user_id,
                            conversation_id=self.run_context.conversation_id,
                        ),
                        message_history=history,
                        event_stream_handler=events,
                        timeout=resolve_run_timeout(
                            self._spec.forwarded_props.run_timeout if self._spec.forwarded_props else None
                        ),
                        conversation_id=self.run_context.conversation_id,
                        run_id=self.run_context.run_id,
                        workspace=(
                            CodingWorkspace(self.run_context.sandbox, conversation_id=self.run_context.conversation_id)
                            if self.run_context.sandbox is not None
                            and self._spec.forwarded_props
                            and self._spec.forwarded_props.smart_search_model
                            else None
                        ),
                    )
                except BaseException:
                    # 用户消息已单独保存，保留工具副作用及中断状态供后续轮次读取
                    partial = captured[len(history) + 1 :]
                    if partial:
                        with anyio.CancelScope(shield=True):
                            await persist_message(
                                AgentMessage(role=AIBuddyMessageRole.assistant, model_messages=repair_messages(partial))
                            )
                    raise
            text = str(result.output or '')
            await persist_message(
                AgentMessage(
                    role=AIBuddyMessageRole.assistant, content=text or None, model_messages=result.new_messages()[1:]
                )
            )
            usage = result.usage
            return AIBuddyMessageStatus.success, AgentUsage(
                input_tokens=int(getattr(usage, 'input_tokens', 0) or 0),
                output_tokens=int(getattr(usage, 'output_tokens', 0) or 0),
                total_tokens=int(getattr(usage, 'total_tokens', 0) or 0),
                cache_read_tokens=int(getattr(usage, 'cache_read_tokens', 0) or 0),
                cache_write_tokens=int(getattr(usage, 'cache_write_tokens', 0) or 0),
                request_count=int(getattr(usage, 'requests', 0) or 0),
                tool_call_count=int(getattr(usage, 'tool_calls', 0) or 0),
            )
        finally:
            with anyio.CancelScope(shield=True):
                try:
                    if model is not None:
                        await adapter.aclose(model)
                finally:
                    await http_client.aclose()

    async def aclose(self) -> None:
        """关闭宿主资源"""
        if self._closed:
            return
        self._closed = True
        try:
            if self._acp_service is not None:
                await self._acp_service.close_all_sessions()
        finally:
            for waiter in self.ui_waiters.values():
                if not waiter.done():
                    waiter.cancel()
            self.ui_waiters.clear()
            if self._spec.close_resources is not None:
                await self._spec.close_resources()


def _bound_tool(
    item: BoundAgentTool,
    *,
    permission_mode: AIBuddyPermissionMode,
    wait_approval: WaitApproval | None,
    tool_policies: dict[str, AIBuddyToolPolicy] | None = None,
    mcp_approve_writes: bool = False,
) -> Tool[Any]:
    """
    绑定工具参数、权限策略与审批回调

    :param item: 工具定义
    :param permission_mode: 权限模式
    :param wait_approval: 权限审批回调
    :param tool_policies: 工具策略
    :param mcp_approve_writes: 是否允许 MCP 写入
    :return:
    """
    default_ask = (
        item.spec.mutating and item.spec.name != 'acp_runner' and permission_mode == AIBuddyPermissionMode.ask
    ) or (item.spec.is_mcp and mcp_approve_writes)
    policy = resolve_tool_policy(
        tool_name=item.spec.name,
        policies=tool_policies,
        default=AIBuddyToolPolicy.ask if default_ask else AIBuddyToolPolicy.allow,
    )
    if item.spec.name == 'run_tests':
        policies = [policy] + [
            resolve_tool_policy(tool_name=name, policies=tool_policies) for name in ('bash', 'write_artifact')
        ]
        priority = {AIBuddyToolPolicy.allow: 0, AIBuddyToolPolicy.ask: 1, AIBuddyToolPolicy.deny: 2}
        policy = max(policies, key=priority.__getitem__)

    async def call(ctx: RunContext[ChatAgentDeps], **kwargs: Any) -> str:
        """
        根据工具策略校验审批并执行工具

        :param ctx: 运行上下文
        :param kwargs: 额外关键字参数
        :return:
        """
        if policy == AIBuddyToolPolicy.deny:
            return f'工具已被拒绝: {item.spec.name}'
        if policy == AIBuddyToolPolicy.ask:
            tool_call = AgentToolCall(id=ctx.tool_call_id or item.spec.name, name=item.spec.name, arguments=kwargs)
            if wait_approval is None or not await wait_approval(item.spec.description, tool_call):
                return '用户未批准此操作，工具未执行'
        # 工具失败要以结果交还模型，否则会中断整轮运行
        try:
            return await item.handler(kwargs)
        except errors.BaseExceptionError as exc:
            return f'错误：{exc.msg}'
        except (SandboxException, WorkspaceError, TimeoutError, OSError, ValueError) as exc:
            log.warning(f'编码工具执行失败 tool={item.spec.name}: {exc!r}')
            return f'错误：工具 {item.spec.name} 执行失败，请检查参数或稍后重试'

    tool = Tool.from_schema(
        call,
        name=item.spec.name,
        description=item.spec.description,
        json_schema=item.spec.parameters,
        takes_ctx=True,
        sequential=True,
        args_validator=build_tool_args_validator(item.spec.parameters),
    )
    # from_schema 默认跳过根类型检查，非对象 JSON 也应进入参数重试而不是触发 TypeError
    tool.function_schema.validator = SchemaValidator(core_schema.dict_schema(strict=True))
    if item.spec.is_mcp:
        tool.metadata = {'ai_buddy_source': 'mcp'}
    return tool
