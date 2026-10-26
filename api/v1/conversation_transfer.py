from typing import Annotated

from fastapi import APIRouter, Path, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.conversation_transfer import (
    AIBuddyConversationTransfer,
    GetAIBuddyConversationImportDetail,
)
from backend.plugin.ai_buddy.service.conversation_transfer_service import ai_buddy_conversation_transfer_service

router = APIRouter()


@router.post(
    '/import',
    summary='导入会话',
    description='导入由导出接口生成的会话文档；文档中的对话 ID 未被占用时保留，否则生成新 ID，附件必须内联携带',
    dependencies=[DependsJwtAuth],
)
async def import_ai_buddy_conversation(
    request: Request,
    db: CurrentSessionTransaction,
    obj: AIBuddyConversationTransfer,
) -> ResponseSchemaModel[GetAIBuddyConversationImportDetail]:
    data = await ai_buddy_conversation_transfer_service.import_conversation(
        db=db, user_id=request.user.id, doc=obj, client=request.headers.get('user-agent')
    )
    return response_base.success(data=data)


@router.get(
    '/{pk}/export',
    summary='导出会话',
    description=('导出为与部署无关的 JSON 文档，附件以内联 base64 携带，尚在生成的消息不会导出'),
    dependencies=[DependsJwtAuth],
)
async def export_ai_buddy_conversation(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[str, Path(description='对话 ID')],
) -> ResponseSchemaModel[AIBuddyConversationTransfer]:
    data = await ai_buddy_conversation_transfer_service.export_conversation(
        db=db,
        user_id=request.user.id,
        conversation_id=pk,
        client=request.headers.get('user-agent'),
    )
    return response_base.success(data=data)
