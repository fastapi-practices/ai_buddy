from fastapi import APIRouter, Request
from pydantic_ai.ui import SSE_CONTENT_TYPE
from starlette.responses import StreamingResponse

from backend.common.security.jwt import DependsJwtAuth
from backend.plugin.ai_buddy.schema.image import AIBuddyImageCompletionParam
from backend.plugin.ai_buddy.service.image_service import ai_buddy_image_service

router = APIRouter()


@router.post(
    '/generations',
    summary='流式生图',
    dependencies=[DependsJwtAuth],
)
async def create_ai_buddy_image_generation(
    request: Request,
    obj: AIBuddyImageCompletionParam,
) -> StreamingResponse:
    return await ai_buddy_image_service.create_generation(
        user_id=request.user.id,
        obj=obj,
        accept=request.headers.get('accept', SSE_CONTENT_TYPE),
    )
