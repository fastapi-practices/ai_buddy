from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from redis_fastapi import cache_evict

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.model import (
    AIBuddyModelAllQueryParam,
    AIBuddyModelQueryParam,
    CreateAIBuddyModelParam,
    CreateAIBuddyModelsParam,
    CreateMyAIBuddyModelParam,
    DeleteAIBuddyModelParam,
    GetAIBuddyModelDetail,
    GetMyAIBuddyModelDetail,
    UpdateAIBuddyModelParam,
    UpdateMyAIBuddyModelParam,
)
from backend.plugin.ai_buddy.schema.model_architecture import GetAIBuddyModelArchitectureSyncDetail
from backend.plugin.ai_buddy.service.model_service import ai_buddy_model_service

router = APIRouter()


@router.get(
    '/all',
    summary='获取所有模型',
    dependencies=[
        Depends(RequestPermission('ai:model:list')),
        DependsRBAC,
    ],
)
async def get_all_ai_buddy_models(
    db: CurrentSession,
    query: Annotated[AIBuddyModelAllQueryParam, Query()],
) -> ResponseSchemaModel[list[GetAIBuddyModelDetail]]:
    data = await ai_buddy_model_service.get_all(
        db=db,
        provider_id=query.provider_id,
        kind=query.kind,
        capability=query.capability,
    )
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取所有模型',
    dependencies=[
        DependsPagination,
        Depends(RequestPermission('ai:model:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_models_paginated(
    db: CurrentSession,
    query: Annotated[AIBuddyModelQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddyModelDetail]]:
    page_data = await ai_buddy_model_service.get_list(
        db=db,
        provider_id=query.provider_id,
        model_id=query.model_id,
        status=query.status,
        kind=query.kind,
        capability=query.capability,
    )
    return response_base.success(data=page_data)


@router.get('/me', summary='获取我的模型', dependencies=[DependsJwtAuth])
async def get_my_ai_buddy_models(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetMyAIBuddyModelDetail]]:
    data = await ai_buddy_model_service.get_mine_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '/me/architecture/sync',
    summary='同步我的模型架构',
    dependencies=[DependsJwtAuth, Depends(cache_evict(eviction_group='ai-model-options'), scope='function')],
)
async def sync_my_ai_buddy_models_architecture(
    request: Request,
    db: CurrentSessionTransaction,
) -> ResponseSchemaModel[GetAIBuddyModelArchitectureSyncDetail]:
    data = await ai_buddy_model_service.sync_user_architecture(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get('/me/{pk}', summary='获取我的模型详情', dependencies=[DependsJwtAuth])
async def get_my_ai_buddy_model(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='模型 ID')],
) -> ResponseSchemaModel[GetMyAIBuddyModelDetail]:
    data = await ai_buddy_model_service.get_mine(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取模型详情',
    dependencies=[
        Depends(RequestPermission('ai:model:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_model(
    db: CurrentSession, pk: Annotated[int, Path(description='模型 ID')]
) -> ResponseSchemaModel[GetAIBuddyModelDetail]:
    data = await ai_buddy_model_service.get(db=db, pk=pk)
    return response_base.success(data=data)


@router.post(
    '/me',
    summary='创建我的模型',
    dependencies=[DependsJwtAuth, Depends(cache_evict(eviction_group='ai-model-options'), scope='function')],
)
async def create_my_ai_buddy_model(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateMyAIBuddyModelParam,
) -> ResponseModel:
    await ai_buddy_model_service.create_mine(db=db, obj=obj, user_id=request.user.id)
    return response_base.success()


@router.post(
    '',
    summary='创建模型',
    dependencies=[
        Depends(RequestPermission('ai:model:add')),
        DependsRBAC,
        Depends(cache_evict(eviction_group='ai-model-options'), scope='function'),
    ],
)
async def create_ai_buddy_model(db: CurrentSessionTransaction, obj: CreateAIBuddyModelParam) -> ResponseModel:
    await ai_buddy_model_service.create(db=db, obj=obj)
    return response_base.success()


@router.post(
    '/architecture/sync',
    summary='同步后台模型架构',
    dependencies=[
        Depends(RequestPermission('ai:model:edit')),
        DependsRBAC,
        Depends(cache_evict(eviction_group='ai-model-options'), scope='function'),
    ],
)
async def sync_ai_buddy_models_architecture(
    db: CurrentSessionTransaction,
) -> ResponseSchemaModel[GetAIBuddyModelArchitectureSyncDetail]:
    data = await ai_buddy_model_service.sync_backend_architecture(db=db)
    return response_base.success(data=data)


@router.post(
    '/batch',
    summary='批量创建模型',
    dependencies=[
        Depends(RequestPermission('ai:model:add')),
        DependsRBAC,
        Depends(cache_evict(eviction_group='ai-model-options'), scope='function'),
    ],
)
async def create_ai_buddy_models(db: CurrentSessionTransaction, obj: CreateAIBuddyModelsParam) -> ResponseModel:
    await ai_buddy_model_service.bulk_create(db=db, obj=obj)
    return response_base.success()


@router.put(
    '/me/{pk}',
    summary='更新我的模型',
    dependencies=[DependsJwtAuth, Depends(cache_evict(eviction_group='ai-model-options'), scope='function')],
)
async def update_my_ai_buddy_model(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='模型 ID')],
    obj: UpdateMyAIBuddyModelParam,
) -> ResponseModel:
    count = await ai_buddy_model_service.update_mine(db=db, pk=pk, obj=obj, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.put(
    '/{pk}',
    summary='更新模型',
    dependencies=[
        Depends(RequestPermission('ai:model:edit')),
        DependsRBAC,
        Depends(cache_evict(eviction_group='ai-model-options'), scope='function'),
    ],
)
async def update_ai_buddy_model(
    db: CurrentSessionTransaction, pk: Annotated[int, Path(description='模型 ID')], obj: UpdateAIBuddyModelParam
) -> ResponseModel:
    count = await ai_buddy_model_service.update(db=db, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/me/{pk}',
    summary='删除我的模型',
    dependencies=[DependsJwtAuth, Depends(cache_evict(eviction_group='ai-model-options'), scope='function')],
)
async def delete_my_ai_buddy_model(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='模型 ID')],
) -> ResponseModel:
    count = await ai_buddy_model_service.delete_mine(db=db, pk=pk, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '',
    summary='批量删除模型',
    dependencies=[
        Depends(RequestPermission('ai:model:del')),
        DependsRBAC,
        Depends(cache_evict(eviction_group='ai-model-options'), scope='function'),
    ],
)
async def delete_ai_buddy_models(db: CurrentSessionTransaction, obj: DeleteAIBuddyModelParam) -> ResponseModel:
    count = await ai_buddy_model_service.delete(db=db, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()
