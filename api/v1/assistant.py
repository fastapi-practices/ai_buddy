from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.enums import ASSISTANT_CATEGORY_META
from backend.plugin.ai_buddy.model.assistant import SYSTEM_ASSISTANT_USER_ID
from backend.plugin.ai_buddy.schema.assistant import (
    AIBuddyAssistantQueryParam,
    AIBuddyAssistantSortQueryParam,
    CreateAIBuddyAssistantParam,
    GetAIBuddyAssistantCategoryDetail,
    GetAIBuddyAssistantDetail,
    UpdateAIBuddyAssistantParam,
)
from backend.plugin.ai_buddy.service.assistant_service import ai_buddy_assistant_service

router = APIRouter()


@router.get('/categories', summary='获取助手分类', dependencies=[DependsJwtAuth])
async def get_ai_buddy_assistant_categories() -> ResponseSchemaModel[list[GetAIBuddyAssistantCategoryDetail]]:
    return response_base.success(data=list(ASSISTANT_CATEGORY_META))


@router.get('/all', summary='获取所有助手', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_assistants(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyAssistantSortQueryParam, Query()],
) -> ResponseSchemaModel[list[GetAIBuddyAssistantDetail]]:
    data = await ai_buddy_assistant_service.get_all(db=db, user_id=request.user.id, sort_type=query.sort_type)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取所有助手',
    dependencies=[
        DependsPagination,
        Depends(RequestPermission('ai:assistant:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_assistants_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyAssistantQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddyAssistantDetail]]:
    page_data = await ai_buddy_assistant_service.get_list(
        db=db,
        user_id=request.user.id,
        name=query.name,
        category=query.category,
        sort_type=query.sort_type,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=page_data)


@router.get(
    '/{pk}',
    summary='获取助手详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_assistant(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='助手 ID')],
) -> ResponseSchemaModel[GetAIBuddyAssistantDetail]:
    data = await ai_buddy_assistant_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建助手',
    dependencies=[
        Depends(RequestPermission('ai:assistant:add')),
        DependsRBAC,
    ],
)
async def create_ai_buddy_assistant(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyAssistantParam,
) -> ResponseModel:
    await ai_buddy_assistant_service.create(db=db, obj=obj, user_id=SYSTEM_ASSISTANT_USER_ID)
    return response_base.success()


@router.post(
    '/me',
    summary='创建我的助手',
    dependencies=[DependsJwtAuth],
)
async def create_my_ai_buddy_assistant(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyAssistantParam,
) -> ResponseModel:
    await ai_buddy_assistant_service.create(db=db, obj=obj, user_id=request.user.id)
    return response_base.success()


@router.put(
    '/me/{pk}',
    summary='更新我的助手',
    dependencies=[DependsJwtAuth],
)
async def update_my_ai_buddy_assistant(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='助手 ID')],
    obj: UpdateAIBuddyAssistantParam,
) -> ResponseModel:
    count = await ai_buddy_assistant_service.update(
        db=db,
        pk=pk,
        obj=obj,
        user_id=request.user.id,
        is_superuser=False,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.put(
    '/{pk}',
    summary='更新助手',
    dependencies=[
        Depends(RequestPermission('ai:assistant:edit')),
        DependsRBAC,
    ],
)
async def update_ai_buddy_assistant(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='助手 ID')],
    obj: UpdateAIBuddyAssistantParam,
) -> ResponseModel:
    count = await ai_buddy_assistant_service.update(
        db=db,
        pk=pk,
        obj=obj,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/me/{pk}',
    summary='删除我的助手',
    dependencies=[DependsJwtAuth],
)
async def delete_my_ai_buddy_assistant(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='助手 ID')],
) -> ResponseModel:
    count = await ai_buddy_assistant_service.delete(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=False,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}',
    summary='删除助手',
    dependencies=[
        Depends(RequestPermission('ai:assistant:del')),
        DependsRBAC,
    ],
)
async def delete_ai_buddy_assistant(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='助手 ID')],
) -> ResponseModel:
    count = await ai_buddy_assistant_service.delete(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
