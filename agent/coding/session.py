from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai.messages import BinaryContent

from backend.common.context import ctx as request_ctx
from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.coding.protocol.acp.bridge import get_bridge
from backend.plugin.ai_buddy.agent.coding.protocol.base import CodingHostSpec
from backend.plugin.ai_buddy.agent.coding.protocol.pydantic_ai.adapter import pydantic_ai_coding_protocol_adapter
from backend.plugin.ai_buddy.agent.coding.sandbox_providers import create_coding_sandbox
from backend.plugin.ai_buddy.agent.coding.tools import BoundAgentTool, build_buddy_resource_tools
from backend.plugin.ai_buddy.agent.coding.types import AgentRunContext, AgentUsage
from backend.plugin.ai_buddy.crud.crud_model import ai_buddy_model_dao
from backend.plugin.ai_buddy.crud.crud_project import ai_buddy_project_dao
from backend.plugin.ai_buddy.crud.crud_provider import ai_buddy_provider_dao
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyMessageStatus,
    AIBuddyModelCapability,
    AIBuddyModelKind,
    AIBuddyPermissionMode,
    AIBuddyProviderType,
)
from backend.plugin.ai_buddy.policy.context import AIBuddyInvocationContext
from backend.plugin.ai_buddy.policy.registry import validate_ai_buddy_invocation
from backend.plugin.ai_buddy.provider.registry import get_provider_adapter
from backend.plugin.ai_buddy.service.workspace_service import ai_buddy_workspace_service
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config
from backend.plugin.ai_buddy.utils.model_catalog import (
    has_model_capability,
    parse_model_capabilities,
    require_model_kind,
)
from backend.plugin.ai_buddy.utils.thinking_policy import resolve_thinking_policy

if TYPE_CHECKING:
    from pydantic_ai.messages import ModelMessage, UserContent
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.plugin.ai_buddy.agent.coding.protocol.base import (
        CancelledCheck,
        CodingHostSession,
        EmitEvent,
        PersistMessage,
        WaitApproval,
    )
    from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam

_SESSION_PLACEHOLDER = object()
_LIVE_SESSIONS: dict[str, CodingSession | object] = {}


class CodingSession:
    """编码运行会话，宿主由协议适配器提供"""

    def __init__(self, host: CodingHostSession) -> None:
        """
        绑定编码宿主与本轮上下文

        :param host: 宿主会话
        :return:
        """
        self._host = host
        self.run_context = host.run_context
        self._closed = False

    def resolve_ui(self, request_id: str, *, approved: bool) -> bool:
        """
        兑现宿主 UI 确认

        :param request_id: 请求 ID
        :param approved: 是否批准
        :return:
        """
        return self._host.resolve_ui(request_id, approved=approved)

    async def wait_ui(self, request_id: str) -> bool:
        """
        等待审批结果

        :param request_id: 请求 ID
        :return:
        """
        return await self._host.wait_ui(request_id)

    async def run(
        self,
        *,
        prompt: str,
        emit: EmitEvent,
        persist_message: PersistMessage,
        is_cancelled: CancelledCheck,
        wait_approval: WaitApproval | None = None,
    ) -> tuple[AIBuddyMessageStatus, AgentUsage]:
        """
        执行本轮提示并映射为 Buddy 编码流

        :param prompt: 用户提示
        :param emit: 事件回调
        :param persist_message: 消息落库
        :param is_cancelled: 取消检查
        :param wait_approval: 审批等待
        :return:
        """
        return await self._host.run(
            prompt=prompt,
            emit=emit,
            persist_message=persist_message,
            is_cancelled=is_cancelled,
            wait_approval=wait_approval,
        )

    async def aclose(self) -> None:
        """幂等关闭宿主并释放会话槽"""
        if self._closed:
            return
        self._closed = True
        _release_live_session(self.run_context.conversation_id, expected=self)
        try:
            await self._host.aclose()
        finally:
            if self.run_context.sandbox is not None:
                await self.run_context.sandbox.stop()


def _release_live_session(conversation_id: str, expected: object | None = None) -> None:
    """
    释放本进程会话槽

    :param conversation_id: 对话 ID
    :param expected: 仅当槽位仍是该对象时释放
    :return:
    """
    current = _LIVE_SESSIONS.get(conversation_id)
    if expected is None:
        if current is _SESSION_PLACEHOLDER:
            _LIVE_SESSIONS.pop(conversation_id, None)
        return
    if current is expected:
        _LIVE_SESSIONS.pop(conversation_id, None)


async def resolve_coding_invocation(
    *,
    db: AsyncSession,
    user_id: int,
    conversation_id: str,
    forwarded_props: AIBuddyChatForwardedPropsParam,
    permission_mode: AIBuddyPermissionMode,
    project_id: int | None,
) -> tuple[object, object, str | None]:
    """
    解析供应商、模型和项目，并校验调用策略

    :param db: 数据库会话
    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :param forwarded_props: 运行扩展参数
    :param permission_mode: 权限模式
    :param project_id: 项目 ID
    :return:
    """
    provider = await ai_buddy_provider_dao.get_visible(db, forwarded_props.provider_id, user_id)
    if not provider:
        raise errors.NotFoundError(msg='供应商不存在')
    if not provider.status:
        raise errors.RequestError(msg='此供应商暂不可用，请更换供应商或联系系统管理员')
    model = await ai_buddy_model_dao.get_by_model_and_provider(
        db, forwarded_props.model_id, forwarded_props.provider_id
    )
    if not model:
        raise errors.NotFoundError(msg='供应商模型不存在')
    if not model.status:
        raise errors.RequestError(msg='此模型暂不可用，请更换模型或联系系统管理员')
    require_model_kind(model, AIBuddyModelKind.chat, msg='编码模式请使用对话模型')
    if not has_model_capability(model, AIBuddyModelCapability.tools):
        raise errors.RequestError(msg='编码模式请使用支持工具的对话模型')
    project_name = None
    if project_id is not None:
        project = await ai_buddy_project_dao.get(db, project_id)
        if project is None or project.user_id != user_id:
            raise errors.NotFoundError(msg='项目不存在')
        project_name = project.name
    invocation_context = AIBuddyInvocationContext(
        provider_id=provider.id,
        provider_type=AIBuddyProviderType(provider.type),
        provider_name=provider.name,
        model_pk=model.id,
        model_id=model.model_id,
        user_id=user_id,
        is_superuser=request_ctx.is_superuser,
        mcp_ids=tuple(forwarded_props.mcp_ids or ()),
        agent_mode=AIBuddyAgentMode.coding,
        conversation_id=conversation_id,
        permission_mode=permission_mode,
    )
    await validate_ai_buddy_invocation(db=db, context=invocation_context)
    get_provider_adapter(provider.type).validate_model_id(model.model_id)
    return provider, model, project_name


async def open_coding_session(
    *,
    db: AsyncSession,
    user_id: int,
    conversation_id: str,
    run_id: str,
    forwarded_props: AIBuddyChatForwardedPropsParam,
    permission_mode: AIBuddyPermissionMode,
    project_id: int | None = None,
    goal: str | None = None,
    message_history: list[ModelMessage] | None = None,
    user_content: list[UserContent] | None = None,
) -> CodingSession:
    """
    解析 Buddy 供应商与模型，打开 Pydantic AI 编码宿主会话

    :param db: 数据库会话
    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :param run_id: 运行 ID
    :param forwarded_props: 运行扩展参数
    :param permission_mode: 权限模式
    :param project_id: 项目 ID
    :param goal: 对话目标
    :param message_history: 编码消息历史
    :param user_content: 本轮用户文本与附件
    :return:
    """
    # 在首次等待前占用槽位，避免并发请求重复启动同一对话
    if conversation_id in _LIVE_SESSIONS:
        raise errors.ConflictError(msg='当前对话正在运行，请稍后再试')
    _LIVE_SESSIONS[conversation_id] = _SESSION_PLACEHOLDER
    host = None
    sandbox = None
    try:
        if forwarded_props.workspace_id is not None:
            await ai_buddy_workspace_service.get(
                db=db,
                user_id=user_id,
                workspace_id=forwarded_props.workspace_id,
            )
        provider, model, project_name = await resolve_coding_invocation(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
            forwarded_props=forwarded_props,
            permission_mode=permission_mode,
            project_id=project_id,
        )
        forwarded_props = resolve_thinking_policy(
            forwarded_props=forwarded_props,
            capabilities=frozenset(parse_model_capabilities(model.capabilities)),
            policy=model.thinking_policy,
        )
        workspace_refs = (
            [forwarded_props.workspace_ref.model_dump()] if forwarded_props.workspace_ref is not None else []
        )
        acp_runner_enabled = bool(forwarded_props.acp_runner)
        acp_cwd = None
        if acp_runner_enabled:
            if not forwarded_props.acp_bridge_id or not forwarded_props.acp_runner_name:
                raise errors.RequestError(msg='请从桌面端连接本地 ACP Agent')
            bridge = await get_bridge(
                bridge_id=forwarded_props.acp_bridge_id, user_id=user_id, runner=forwarded_props.acp_runner_name
            )
            acp_cwd = bridge['cwd']
            sandbox = None
        else:
            await load_ai_buddy_config(db)
            sandbox = await create_coding_sandbox(
                conversation_id=conversation_id,
                user_id=user_id,
                permission_mode=permission_mode,
                execution_backend=forwarded_props.execution_backend,
                execution_bridge_id=forwarded_props.execution_bridge_id,
                sandbox_provider=forwarded_props.sandbox_provider,
            )
        run_context = AgentRunContext(
            user_id=user_id,
            is_superuser=request_ctx.is_superuser,
            conversation_id=conversation_id,
            run_id=run_id,
            permission_mode=permission_mode,
            sandbox=sandbox,
            workspace_id=forwarded_props.workspace_id,
            input_attachments=tuple(item for item in user_content or [] if isinstance(item, BinaryContent)),
            project_name=project_name,
            goal=goal,
            mcp_ids=tuple(forwarded_props.mcp_ids or ()),
            workspace_refs=tuple(workspace_refs),
            acp_runner_enabled=acp_runner_enabled,
            acp_bridge_id=forwarded_props.acp_bridge_id,
            acp_cwd=acp_cwd,
            acp_runner_name=forwarded_props.acp_runner_name,
            tool_policies=dict(forwarded_props.tool_policies or {}),
            mcp_approve_writes=forwarded_props.mcp_approve_writes,
        )
        buddy_tools: list[BoundAgentTool] = build_buddy_resource_tools(run_context)
        if acp_runner_enabled:
            await load_ai_buddy_config(db)
        host = await pydantic_ai_coding_protocol_adapter.open_session(
            spec=CodingHostSpec(
                run_context=run_context,
                buddy_tools=buddy_tools,
                provider_type=AIBuddyProviderType(provider.type),
                model_id=model.model_id,
                api_key=provider.api_key,
                api_host=provider.api_host,
                input_modalities=model.input_modalities,
                context_window=model.context_window,
                workspace_id=run_context.workspace_id,
                forwarded_props=forwarded_props,
                user_content=user_content or [],
                thinking=forwarded_props.thinking,
                message_history=message_history or [],
                compaction_enabled=forwarded_props.compaction_enabled,
                compaction_keep_messages=forwarded_props.compaction_keep_messages,
                compaction_max_messages=forwarded_props.compaction_max_messages,
            )
        )
        session = CodingSession(host)
    except BaseException:
        _release_live_session(conversation_id)
        try:
            if host is not None:
                await host.aclose()
        finally:
            if sandbox is not None:
                await sandbox.stop()
        raise
    _LIVE_SESSIONS[conversation_id] = session
    return session
