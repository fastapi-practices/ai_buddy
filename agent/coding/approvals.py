from __future__ import annotations

import asyncio
import json

from typing import TYPE_CHECKING
from uuid import uuid4

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store
from backend.plugin.ai_buddy.enums import AIBuddyApprovalStatus
from backend.plugin.ai_buddy.service.approval_audit_service import ai_buddy_approval_audit_service

if TYPE_CHECKING:
    from backend.plugin.ai_buddy.agent.coding.protocol.base import CancelledCheck, EmitEvent
    from backend.plugin.ai_buddy.agent.coding.types import AgentToolCall

_RESOLVE_SCRIPT = """
local pending = redis.call('get', KEYS[1])
if not pending or redis.call('exists', KEYS[3]) == 1 then return 0 end
local record = cjson.decode(pending)
if redis.call('get', KEYS[2]) ~= record.run_id or record.status ~= ARGV[2] then return 0 end
record.status = ARGV[1]
redis.call('set', KEYS[1], cjson.encode(record), 'KEEPTTL')
return 1
"""


def _approval_key(conversation_id: str, request_id: str) -> str:
    """构建对话内审批请求的缓存键

    :param conversation_id: 对话 ID
    :param request_id: 请求 ID
    :return:
    """
    return f'{shared_chat_run_store.key_prefix}:{conversation_id}:approval:{request_id}'


async def resolve_approval(*, conversation_id: str, user_id: int, request_id: str, approved: bool) -> None:
    """仅接受当前运行中尚未处理的审批

    :param conversation_id: 对话 ID
    :param user_id: 审批用户 ID
    :param request_id: 请求 ID
    :param approved: 是否批准
    :return:
    """
    accepted = await shared_chat_run_store.client.eval(
        _RESOLVE_SCRIPT,
        3,
        _approval_key(conversation_id, request_id),
        shared_chat_run_store._key(conversation_id, 'owner'),
        shared_chat_run_store._key(conversation_id, 'cancel'),
        AIBuddyApprovalStatus.approved if approved else AIBuddyApprovalStatus.denied,
        AIBuddyApprovalStatus.pending,
    )
    if not accepted:
        raise errors.ConflictError(msg='审批已处理或生成任务已结束')
    await ai_buddy_approval_audit_service.resolve(
        user_id=user_id,
        request_id=request_id,
        status=AIBuddyApprovalStatus.approved if approved else AIBuddyApprovalStatus.denied,
    )


async def wait_for_approval(
    *,
    conversation_id: str,
    user_id: int,
    run_id: str,
    call: AgentToolCall,
    emit: EmitEvent,
    is_cancelled: CancelledCheck,
) -> bool:
    """通过共享存储等待桌面端审批，支持跨进程提交和事件重放

    :param conversation_id: 对话 ID
    :param user_id: 审批用户 ID
    :param run_id: 运行 ID
    :param call: 工具调用
    :param emit: 事件回调
    :param is_cancelled: 取消检查回调
    :return:
    """
    request_id = uuid4().hex
    key = _approval_key(conversation_id, request_id)
    client = shared_chat_run_store.client
    expires_seconds = settings.AI_BUDDY_AGENT_SANDBOX_TIMEOUT_MINUTES * 60 + 60
    await ai_buddy_approval_audit_service.create(
        user_id=user_id,
        conversation_id=conversation_id,
        request_id=request_id,
        run_id=run_id,
        tool_call_id=call.id,
        tool_name=call.name,
        arguments=call.arguments,
        expires_seconds=expires_seconds,
    )
    try:
        await client.set(
            key, json.dumps({'run_id': run_id, 'status': AIBuddyApprovalStatus.pending}), ex=expires_seconds
        )
        await emit(
            'approval',
            {
                'request_id': request_id,
                'call_id': call.id,
                'name': call.name,
                'arguments': call.arguments,
            },
        )
        while not await is_cancelled():
            raw = await client.get(key)
            if not raw:
                return False
            record = json.loads(raw)
            if record['status'] != AIBuddyApprovalStatus.pending:
                approved = record['status'] == AIBuddyApprovalStatus.approved
                await ai_buddy_approval_audit_service.resolve(
                    user_id=user_id,
                    request_id=request_id,
                    status=AIBuddyApprovalStatus.approved if approved else AIBuddyApprovalStatus.denied,
                )
                await emit('approval_resolved', {'request_id': request_id, 'approved': approved})
                return approved
            await asyncio.sleep(0.1)
        return False
    finally:
        try:
            await ai_buddy_approval_audit_service.resolve(
                user_id=user_id,
                request_id=request_id,
                status=AIBuddyApprovalStatus.cancelled if await is_cancelled() else AIBuddyApprovalStatus.expired,
            )
        finally:
            await client.delete(key)
