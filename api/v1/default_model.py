from typing import Annotated

from fastapi import APIRouter, Depends, Path
from redis_fastapi import cache_evict

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.enums import AIBuddyModelKind
from backend.plugin.ai_buddy.schema.default_model import GetAIBuddyDefaultModelDetail, UpdateAIBuddyDefaultModelParam
from backend.plugin.ai_buddy.service.default_model_service import ai_buddy_default_model_service

router = APIRouter()


@router.get('/{kind}', summary='获取默认模型配置', dependencies=[DependsJwtAuth])
async def get_ai_buddy_default_model(
    db: CurrentSession,
    kind: Annotated[AIBuddyModelKind, Path(description='模型类型')],
) -> ResponseSchemaModel[GetAIBuddyDefaultModelDetail]:
    data = await ai_buddy_default_model_service.get_config(db=db, kind=kind)
    return response_base.success(data=data)


@router.put(
    '/{kind}',
    summary='更新默认模型配置',
    dependencies=[
        Depends(RequestPermission('ai:default-model:edit')),
        DependsRBAC,
        Depends(cache_evict(eviction_group='ai-model-options'), scope='function'),
    ],
)
async def update_ai_buddy_default_model(
    db: CurrentSessionTransaction,
    kind: Annotated[AIBuddyModelKind, Path(description='模型类型')],
    obj: UpdateAIBuddyDefaultModelParam,
) -> ResponseModel:
    await ai_buddy_default_model_service.update(db=db, kind=kind, obj=obj)
    return response_base.success()
