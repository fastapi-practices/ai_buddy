from fastapi import APIRouter, Depends, Request
from redis_fastapi import cache

from backend.common.cache import http_cache_key
from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.core.conf import settings
from backend.database.db import CurrentSession
from backend.plugin.ai_buddy.schema.model_option import GetAIBuddyModelOptionDetail
from backend.plugin.ai_buddy.service.model_option_service import ai_buddy_model_option_service

router = APIRouter()


@router.get(
    '',
    summary='获取模型选项',
    dependencies=[
        DependsJwtAuth,
        Depends(
            cache(
                ttl=settings.HTTP_CACHE_TTL,
                eviction_group='ai-model-options',
                key_builder=http_cache_key,
                no_store=True,
            )
        ),
    ],
)
async def get_ai_buddy_model_options(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[GetAIBuddyModelOptionDetail]:
    data = await ai_buddy_model_option_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)
