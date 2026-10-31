from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from pydantic_ai.ui import SSE_CONTENT_TYPE
from starlette.responses import StreamingResponse

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatRegenerateParam
from backend.plugin.ai_buddy.schema.message_history import (
    AIBuddyMessageHistoryQueryParam,
    AIBuddyMessageSearchQueryParam,
    GetAIBuddyMessagePageDetail,
    GetAIBuddyMessageSearchDetail,
    GetAIBuddyMessageVersionDetail,
)
from backend.plugin.ai_buddy.service.message_history_service import ai_buddy_message_history_service
from backend.plugin.ai_buddy.service.message_service import ai_buddy_message_service

router = APIRouter()


@router.get('/{conversation_id}/messages', summary='分页读取历史消息', dependencies=[DependsJwtAuth])
async def get_ai_buddy_message_history(
    request: Request,
    db: CurrentSession,
    conversation_id: str,
    query: Annotated[AIBuddyMessageHistoryQueryParam, Query()],
) -> ResponseSchemaModel[GetAIBuddyMessagePageDetail]:
    data = await ai_buddy_message_history_service.page(
        db=db,
        conversation_id=conversation_id,
        user_id=request.user.id,
        before=query.before,
        limit=query.limit,
    )
    return response_base.success(data=data)


@router.get('/{conversation_id}/messages/search', summary='检索全部历史正文', dependencies=[DependsJwtAuth])
async def search_ai_buddy_message_history(
    request: Request,
    db: CurrentSession,
    conversation_id: str,
    query: Annotated[AIBuddyMessageSearchQueryParam, Query()],
) -> ResponseSchemaModel[GetAIBuddyMessageSearchDetail]:
    data = await ai_buddy_message_history_service.search(
        db=db,
        conversation_id=conversation_id,
        user_id=request.user.id,
        q=query.q,
        cursor=query.cursor,
        limit=query.limit,
    )
    return response_base.success(data=data)


@router.get('/{conversation_id}/messages/{pk}/versions', summary='获取消息分支版本', dependencies=[DependsJwtAuth])
async def get_ai_buddy_message_versions(
    request: Request,
    db: CurrentSession,
    conversation_id: str,
    pk: Annotated[int, Path(description='消息 ID')],
) -> ResponseSchemaModel[list[GetAIBuddyMessageVersionDetail]]:
    data = await ai_buddy_message_history_service.versions(
        db=db, conversation_id=conversation_id, user_id=request.user.id, message_id=pk
    )
    return response_base.success(data=data)


@router.post(
    '/{conversation_id}/messages/{pk}/regenerate',
    summary='根据最后一条用户消息重发',
    dependencies=[DependsJwtAuth],
)
async def regenerate_ai_buddy_conversation_message(
    request: Request,
    conversation_id: Annotated[str, Path(description='对话 ID')],
    pk: Annotated[int, Path(description='消息 ID')],
    obj: AIBuddyChatRegenerateParam,
) -> StreamingResponse:
    return await ai_buddy_message_service.regenerate_from_user_message(
        user_id=request.user.id,
        conversation_id=conversation_id,
        pk=pk,
        obj=obj,
        accept=request.headers.get('accept', SSE_CONTENT_TYPE),
    )


@router.delete(
    '/{conversation_id}/messages',
    summary='清空对话消息',
    dependencies=[DependsJwtAuth],
)
async def clear_ai_buddy_conversation_messages(
    request: Request,
    db: CurrentSessionTransaction,
    conversation_id: Annotated[str, Path(description='对话 ID')],
) -> ResponseModel:
    count = await ai_buddy_message_service.clear(
        db=db,
        user_id=request.user.id,
        conversation_id=conversation_id,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{conversation_id}/messages/{pk}',
    summary='删除指定消息',
    dependencies=[DependsJwtAuth],
)
async def delete_ai_buddy_conversation_message(
    request: Request,
    db: CurrentSessionTransaction,
    conversation_id: Annotated[str, Path(description='对话 ID')],
    pk: Annotated[int, Path(description='消息 ID')],
) -> ResponseModel:
    count = await ai_buddy_message_service.delete(
        db=db,
        user_id=request.user.id,
        conversation_id=conversation_id,
        pk=pk,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
