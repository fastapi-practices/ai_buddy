from fastapi import APIRouter, Request
from pydantic_ai.ui import SSE_CONTENT_TYPE
from starlette.responses import StreamingResponse

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.plugin.ai_buddy.schema.chat import (
    AIBuddyChatCompletionParam,
    AIBuddyChatPolishParam,
    GetAIBuddyChatPolishDetail,
)
from backend.plugin.ai_buddy.service.chat_polish_service import ai_buddy_chat_polish_service
from backend.plugin.ai_buddy.service.chat_service import ai_buddy_chat_service

router = APIRouter()


@router.post(
    '/polish',
    summary='润色输入框草稿',
    dependencies=[DependsJwtAuth],
)
async def polish_ai_buddy_chat_prompt(
    request: Request,
    obj: AIBuddyChatPolishParam,
) -> ResponseSchemaModel[GetAIBuddyChatPolishDetail]:
    data = await ai_buddy_chat_polish_service.polish(user_id=request.user.id, obj=obj)
    return response_base.success(data=data)


@router.post(
    '/completions',
    summary='流式对话',
    dependencies=[DependsJwtAuth],
)
async def create_ai_buddy_chat_completion(
    request: Request,
    obj: AIBuddyChatCompletionParam,
) -> StreamingResponse:
    return await ai_buddy_chat_service.create_completion(
        user_id=request.user.id,
        obj=obj,
        accept=request.headers.get('accept', SSE_CONTENT_TYPE),
    )
