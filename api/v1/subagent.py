from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.subagent import (
    AIBuddySubagentQueryParam,
    CreateAIBuddySubagentParam,
    GetAIBuddySubagentDetail,
    UpdateAIBuddySubagentParam,
)
from backend.plugin.ai_buddy.service.subagent_service import ai_buddy_subagent_service
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID

router = APIRouter()


@router.get('/all', summary='获取所有子代理', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_subagents(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetAIBuddySubagentDetail]]:
    data = await ai_buddy_subagent_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取所有子代理',
    dependencies=[
        DependsPagination,
        Depends(RequestPermission('ai:subagent:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_subagents_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddySubagentQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddySubagentDetail]]:
    page_data = await ai_buddy_subagent_service.get_list(
        db=db,
        user_id=request.user.id,
        name=query.name,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=page_data)


@router.get(
    '/{pk}',
    summary='获取子代理详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_subagent(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='子代理 ID')],
) -> ResponseSchemaModel[GetAIBuddySubagentDetail]:
    data = await ai_buddy_subagent_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建子代理',
    dependencies=[
        Depends(RequestPermission('ai:subagent:add')),
        DependsRBAC,
    ],
)
async def create_ai_buddy_subagent(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddySubagentParam,
) -> ResponseModel:
    await ai_buddy_subagent_service.create(db=db, obj=obj, user_id=SYSTEM_OWNER_USER_ID)
    return response_base.success()


@router.post(
    '/me',
    summary='创建我的子代理',
    dependencies=[DependsJwtAuth],
)
async def create_my_ai_buddy_subagent(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddySubagentParam,
) -> ResponseModel:
    await ai_buddy_subagent_service.create(db=db, obj=obj, user_id=request.user.id)
    return response_base.success()


@router.put(
    '/me/{pk}',
    summary='更新我的子代理',
    dependencies=[DependsJwtAuth],
)
async def update_my_ai_buddy_subagent(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='子代理 ID')],
    obj: UpdateAIBuddySubagentParam,
) -> ResponseModel:
    count = await ai_buddy_subagent_service.update(
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
    summary='更新子代理',
    dependencies=[
        Depends(RequestPermission('ai:subagent:edit')),
        DependsRBAC,
    ],
)
async def update_ai_buddy_subagent(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='子代理 ID')],
    obj: UpdateAIBuddySubagentParam,
) -> ResponseModel:
    count = await ai_buddy_subagent_service.update(
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
    summary='删除我的子代理',
    dependencies=[DependsJwtAuth],
)
async def delete_my_ai_buddy_subagent(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='子代理 ID')],
) -> ResponseModel:
    count = await ai_buddy_subagent_service.delete(
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
    summary='删除子代理',
    dependencies=[
        Depends(RequestPermission('ai:subagent:del')),
        DependsRBAC,
    ],
)
async def delete_ai_buddy_subagent(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='子代理 ID')],
) -> ResponseModel:
    count = await ai_buddy_subagent_service.delete(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
