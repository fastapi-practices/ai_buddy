from typing import Annotated

from fastapi import APIRouter, Query, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.conversation_audit import (
    AIBuddyConversationAuditQueryParam,
    GetAIBuddyConversationAuditDetail,
)
from backend.plugin.ai_buddy.schema.sync import AIBuddySyncQueryParam, GetAIBuddySyncDetail
from backend.plugin.ai_buddy.service.conversation_audit_service import ai_buddy_conversation_audit_service
from backend.plugin.ai_buddy.service.sync_service import ai_buddy_sync_service

router = APIRouter()


@router.get(
    '/changes',
    summary='增量拉取对话与消息变更',
    description=(
        '按游标拉取当前用户的对话和消息变更，已删除的对话和消息以 delete 墓碑返回；'
        'has_more 为 true 时用 next_cursor 继续拉取，客户端按实体行 ID 幂等合并'
    ),
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_sync_changes(
    request: Request, db: CurrentSessionTransaction, query: Annotated[AIBuddySyncQueryParam, Query()]
) -> ResponseSchemaModel[GetAIBuddySyncDetail]:
    data = await ai_buddy_sync_service.get_changes(
        db=db,
        user_id=request.user.id,
        cursor=query.cursor,
        limit=query.limit,
        client=request.headers.get('user-agent'),
    )
    return response_base.success(data=data)


@router.get(
    '/audits',
    summary='获取当前用户的会话审计',
    description='记录会话导出、导入、删除和同步访问，包含已删除会话的记录',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_conversation_audits(
    request: Request, db: CurrentSession, query: Annotated[AIBuddyConversationAuditQueryParam, Query()]
) -> ResponseSchemaModel[list[GetAIBuddyConversationAuditDetail]]:
    data = await ai_buddy_conversation_audit_service.get_all(
        db=db, user_id=request.user.id, conversation_id=query.conversation_id, before=query.before, limit=query.limit
    )
    return response_base.success(data=data)
