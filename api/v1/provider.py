from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from redis_fastapi import cache_evict

from backend.common.pagination import CursorPageData, DependsCursorPagination
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.provider import (
    AIBuddyProviderQueryParam,
    CreateAIBuddyProviderParam,
    CreateMyAIBuddyProviderParam,
    DeleteAIBuddyProviderParam,
    GetAIBuddyProviderDetail,
    GetAIBuddyProviderModelDetail,
    GetMyAIBuddyProviderDetail,
    UpdateAIBuddyProviderParam,
    UpdateMyAIBuddyProviderParam,
)
from backend.plugin.ai_buddy.service.provider_service import ai_buddy_provider_service

router = APIRouter()


@router.get(
    '/all',
    summary='获取所有供应商',
    dependencies=[
        Depends(RequestPermission('ai:provider:list')),
        DependsRBAC,
    ],
)
async def get_all_ai_buddy_providers(db: CurrentSession) -> ResponseSchemaModel[list[GetAIBuddyProviderDetail]]:
    data = await ai_buddy_provider_service.get_all(db=db)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取所有供应商',
    dependencies=[
        DependsCursorPagination,
        Depends(RequestPermission('ai:provider:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_providers_paginated(
    db: CurrentSession,
    query: Annotated[AIBuddyProviderQueryParam, Query()],
) -> ResponseSchemaModel[CursorPageData[GetAIBuddyProviderDetail]]:
    page_data = await ai_buddy_provider_service.get_list(
        db=db,
        name=query.name,
        type=query.type,
        status=query.status,
    )
    return response_base.success(data=page_data)


@router.get('/me', summary='获取我的供应商', dependencies=[DependsJwtAuth])
async def get_my_ai_buddy_providers(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetMyAIBuddyProviderDetail]]:
    data = await ai_buddy_provider_service.get_mine_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get('/me/{pk}', summary='获取我的供应商详情', dependencies=[DependsJwtAuth])
async def get_my_ai_buddy_provider(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='供应商 ID')],
) -> ResponseSchemaModel[GetMyAIBuddyProviderDetail]:
    data = await ai_buddy_provider_service.get_mine(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.get('/me/{pk}/models', summary='获取我的供应商模型列表', dependencies=[DependsJwtAuth])
async def get_my_ai_buddy_provider_models(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='供应商 ID')],
) -> ResponseSchemaModel[list[GetAIBuddyProviderModelDetail]]:
    data = await ai_buddy_provider_service.get_mine_models(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取供应商详情',
    dependencies=[
        Depends(RequestPermission('ai:provider:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_provider(
    db: CurrentSession, pk: Annotated[int, Path(description='供应商 ID')]
) -> ResponseSchemaModel[GetAIBuddyProviderDetail]:
    data = await ai_buddy_provider_service.get(db=db, pk=pk)
    return response_base.success(data=data)


@router.get(
    '/{pk}/models',
    summary='获取供应商模型列表',
    dependencies=[
        Depends(RequestPermission('ai:provider:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_provider_models(
    db: CurrentSession,
    pk: Annotated[int, Path(description='供应商 ID')],
) -> ResponseSchemaModel[list[GetAIBuddyProviderModelDetail]]:
    data = await ai_buddy_provider_service.get_models(db=db, pk=pk)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建供应商',
    dependencies=[
        Depends(RequestPermission('ai:provider:add')),
        DependsRBAC,
        Depends(cache_evict(eviction_group='ai-model-options'), scope='function'),
    ],
)
async def create_ai_buddy_provider(db: CurrentSessionTransaction, obj: CreateAIBuddyProviderParam) -> ResponseModel:
    await ai_buddy_provider_service.create(db=db, obj=obj)
    return response_base.success()


@router.post(
    '/me',
    summary='创建我的供应商',
    dependencies=[DependsJwtAuth, Depends(cache_evict(eviction_group='ai-model-options'), scope='function')],
)
async def create_my_ai_buddy_provider(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateMyAIBuddyProviderParam,
) -> ResponseModel:
    await ai_buddy_provider_service.create_mine(db=db, obj=obj, user_id=request.user.id)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新供应商',
    dependencies=[
        Depends(RequestPermission('ai:provider:edit')),
        DependsRBAC,
        Depends(cache_evict(eviction_group='ai-model-options'), scope='function'),
    ],
)
async def update_ai_buddy_provider(
    db: CurrentSessionTransaction, pk: Annotated[int, Path(description='供应商 ID')], obj: UpdateAIBuddyProviderParam
) -> ResponseModel:
    count = await ai_buddy_provider_service.update(db=db, pk=pk, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.put(
    '/me/{pk}',
    summary='更新我的供应商',
    dependencies=[DependsJwtAuth, Depends(cache_evict(eviction_group='ai-model-options'), scope='function')],
)
async def update_my_ai_buddy_provider(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='供应商 ID')],
    obj: UpdateMyAIBuddyProviderParam,
) -> ResponseModel:
    count = await ai_buddy_provider_service.update_mine(db=db, pk=pk, obj=obj, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '',
    summary='批量删除供应商',
    dependencies=[
        Depends(RequestPermission('ai:provider:del')),
        DependsRBAC,
        Depends(cache_evict(eviction_group='ai-model-options'), scope='function'),
    ],
)
async def delete_ai_buddy_providers(db: CurrentSessionTransaction, obj: DeleteAIBuddyProviderParam) -> ResponseModel:
    count = await ai_buddy_provider_service.delete(db=db, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/me',
    summary='删除我的供应商',
    dependencies=[DependsJwtAuth, Depends(cache_evict(eviction_group='ai-model-options'), scope='function')],
)
async def delete_my_ai_buddy_providers(
    request: Request,
    db: CurrentSessionTransaction,
    obj: DeleteAIBuddyProviderParam,
) -> ResponseModel:
    count = await ai_buddy_provider_service.delete_mine(db=db, obj=obj, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()
