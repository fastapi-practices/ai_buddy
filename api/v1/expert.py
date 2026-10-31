from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.expert import (
    AIBuddyExpertQueryParam,
    ApplyAIBuddyExpertParam,
    CreateAIBuddyExpertParam,
    GetAIBuddyExpertDetail,
    GetAIBuddyExpertWithRelationDetail,
    UpdateAIBuddyExpertParam,
)
from backend.plugin.ai_buddy.service.expert_service import ai_buddy_expert_service
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID

router = APIRouter()


@router.get('/all', summary='获取所有专家模板', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_experts(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetAIBuddyExpertDetail]]:
    data = await ai_buddy_expert_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取所有专家模板',
    dependencies=[
        DependsPagination,
        Depends(RequestPermission('ai:expert:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_experts_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyExpertQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddyExpertDetail]]:
    page_data = await ai_buddy_expert_service.get_list(
        db=db,
        user_id=request.user.id,
        name=query.name,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=page_data)


@router.get(
    '/{pk}',
    summary='获取专家模板详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_expert(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='专家 ID')],
) -> ResponseSchemaModel[GetAIBuddyExpertWithRelationDetail]:
    data = await ai_buddy_expert_service.get_with_relation(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建专家模板',
    dependencies=[
        Depends(RequestPermission('ai:expert:add')),
        DependsRBAC,
    ],
)
async def create_ai_buddy_expert(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyExpertParam,
) -> ResponseModel:
    await ai_buddy_expert_service.create(db=db, obj=obj, user_id=SYSTEM_OWNER_USER_ID)
    return response_base.success()


@router.post(
    '/me',
    summary='创建我的专家模板',
    dependencies=[DependsJwtAuth],
)
async def create_my_ai_buddy_expert(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyExpertParam,
) -> ResponseModel:
    await ai_buddy_expert_service.create(db=db, obj=obj, user_id=request.user.id)
    return response_base.success()


@router.put(
    '/me/{pk}',
    summary='更新我的专家模板',
    dependencies=[DependsJwtAuth],
)
async def update_my_ai_buddy_expert(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='专家 ID')],
    obj: UpdateAIBuddyExpertParam,
) -> ResponseModel:
    count = await ai_buddy_expert_service.update(
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
    summary='更新专家模板',
    dependencies=[
        Depends(RequestPermission('ai:expert:edit')),
        DependsRBAC,
    ],
)
async def update_ai_buddy_expert(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='专家 ID')],
    obj: UpdateAIBuddyExpertParam,
) -> ResponseModel:
    count = await ai_buddy_expert_service.update(
        db=db,
        pk=pk,
        obj=obj,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post(
    '/{pk}/apply',
    summary='用专家模板创建助手',
    dependencies=[DependsJwtAuth],
)
async def apply_ai_buddy_expert(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='专家 ID')],
    obj: ApplyAIBuddyExpertParam,
) -> ResponseSchemaModel[dict]:
    data = await ai_buddy_expert_service.apply_to_assistant(
        db=db,
        pk=pk,
        user_id=request.user.id,
        name=obj.name,
    )
    return response_base.success(data=data)


@router.delete(
    '/me/{pk}',
    summary='删除我的专家模板',
    dependencies=[DependsJwtAuth],
)
async def delete_my_ai_buddy_expert(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='专家 ID')],
) -> ResponseModel:
    count = await ai_buddy_expert_service.delete(
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
    summary='删除专家模板',
    dependencies=[
        Depends(RequestPermission('ai:expert:del')),
        DependsRBAC,
    ],
)
async def delete_ai_buddy_expert(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='专家 ID')],
) -> ResponseModel:
    count = await ai_buddy_expert_service.delete(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
