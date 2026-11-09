import asyncio

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic_ai_harness.step_persistence.recovery import inspect_recovery

from backend.app.admin.crud.crud_user import user_dao
from backend.common.log import log
from backend.database.db import async_db_session, uuid4_str
from backend.plugin.ai_buddy.agent.durability.config import (
    durability_enabled,
    durability_recovery_enabled,
    durability_recovery_interval_seconds,
    durability_stale_seconds,
)
from backend.plugin.ai_buddy.agent.step_store import ai_buddy_step_store
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store
from backend.plugin.ai_buddy.agent.work.runs import has_active_run
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.crud.crud_step_run import ai_buddy_step_run_dao
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyChatGenerationType,
    AIBuddyExecutionBackend,
    AIBuddyMessageRole,
    AIBuddyPermissionMode,
    AIBuddyWebSearchType,
)
from backend.utils.timezone import timezone

_RECOVERY_LIMIT = 50
"""单轮巡检最多恢复的对话数量"""

_recovery_tasks: set[asyncio.Task[None]] = set()
"""在途恢复任务，避免被垃圾回收"""


@dataclass(frozen=True, slots=True)
class RecoveryContext:
    """可恢复的对话运行上下文"""

    conversation_id: str
    user_id: int
    is_superuser: bool
    assistant_message_id: int
    title: str
    origin: str
    forwarded_props: dict[str, Any]
    message_history: list[Any]


def _build_forwarded_props(*, conversation: Any, turn_context: dict[str, Any] | None) -> dict[str, Any]:
    """
    按会话与本轮组合重建扩展参数

    :param conversation: 会话记录
    :param turn_context: 本轮实际组合
    :return:
    """
    context = turn_context or {}
    return {
        'generation_type': context.get('generation_type') or AIBuddyChatGenerationType.text,
        'provider_id': conversation.provider_id,
        'model_id': conversation.model_id,
        'assistant_id': conversation.assistant_id,
        'project_id': conversation.project_id,
        'agent_mode': context.get('agent_mode') or conversation.agent_mode or AIBuddyAgentMode.work,
        'mcp_ids': context.get('mcp_ids') or [],
        'thinking': context.get('thinking'),
        'web_search': context.get('web_search') or AIBuddyWebSearchType.off,
        'execution_backend': context.get('execution_backend') or AIBuddyExecutionBackend.local,
        'workspace_id': context.get('workspace_id'),
        'workspace_ref': context.get('workspace_ref'),
        'permission_mode': context.get('permission_mode') or AIBuddyPermissionMode.ask,
        'acp_runner': context.get('acp_runner'),
        'acp_runner_name': context.get('acp_runner_name'),
    }


async def load_recovery_context(*, conversation_id: str, assistant_message_id: int) -> RecoveryContext | None:
    """
    读取可恢复的运行上下文，没有可用快照或存在状态未知的工具副作用时返回空

    :param conversation_id: 对话 ID
    :param assistant_message_id: 未完成的助手消息 ID
    :return:
    """
    async with async_db_session() as db:
        runs = await ai_buddy_step_run_dao.get_list(db, parent_run_id=None, conversation_id=conversation_id)
        conversation = await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
        message = await ai_buddy_message_dao.get(db, assistant_message_id)
        user = await user_dao.get(db, conversation.user_id) if conversation is not None else None
    if not runs or conversation is None or message is None or user is None:
        return None
    generation_type = (message.turn_context or {}).get('generation_type')
    if generation_type != AIBuddyChatGenerationType.text:
        return None

    inspection = await inspect_recovery(store=ai_buddy_step_store, run_id=runs[-1].run_id)
    if inspection.latest is None:
        return None
    unresolved_tools = tuple(record.tool_name for record in inspection.unresolved)
    if unresolved_tools:
        log.warning(f'对话存在状态未知的工具副作用，跳过恢复 conversation_id={conversation_id}')
        log.warning(f'状态未知的工具：{list(unresolved_tools)}')
        return None

    return RecoveryContext(
        conversation_id=conversation_id,
        user_id=conversation.user_id,
        is_superuser=bool(user.is_superuser),
        assistant_message_id=assistant_message_id,
        title=conversation.title or '',
        origin=str(message.origin or 'web'),
        forwarded_props=_build_forwarded_props(conversation=conversation, turn_context=message.turn_context),
        message_history=list(inspection.latest.messages),
    )


async def _recover_interrupted_runs() -> int:
    """
    扫描被中断的对话生成并派发恢复任务，返回派发数量

    :return:
    """
    # 延迟导入续跑模块，避免与恢复上下文模块循环引用
    from backend.plugin.ai_buddy.agent.durability.resume import resume_interrupted_run

    if not durability_enabled() or not durability_recovery_enabled():
        return 0
    stale_before = timezone.now() - timedelta(seconds=durability_stale_seconds())
    async with async_db_session() as db:
        stale_rows = await ai_buddy_message_dao.get_stale_pending(db, stale_before)

    recovered = 0
    for row in stale_rows[:_RECOVERY_LIMIT]:
        if row.role != AIBuddyMessageRole.assistant:
            continue
        if await has_active_run(row.conversation_id):
            continue
        context = await load_recovery_context(
            conversation_id=row.conversation_id,
            assistant_message_id=row.id,
        )
        if context is None:
            continue
        run_id = uuid4_str()
        if not await shared_chat_run_store.claim(conversation_id=row.conversation_id, run_id=run_id):
            continue
        task = asyncio.create_task(
            resume_interrupted_run(context=context, run_id=run_id),
            name=f'ai-buddy-recovery-{row.conversation_id}',
        )
        _recovery_tasks.add(task)
        task.add_done_callback(_recovery_tasks.discard)
        recovered += 1
        log.info(f'已派发容灾恢复任务 conversation_id={row.conversation_id}')
    return recovered


async def recovery_loop() -> None:
    """周期扫描并恢复被中断的对话生成"""
    while True:
        try:
            recovered = await _recover_interrupted_runs()
            if recovered:
                log.info(f'已恢复 {recovered} 个被中断的对话生成')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(f'扫描容灾恢复任务失败: {exc}')
        await asyncio.sleep(durability_recovery_interval_seconds())
