from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.permission import (
    AIBuddyPermissionProfileQueryParam,
    CopyAIBuddyPermissionProfileParam,
    CreateAIBuddyPermissionProfileParam,
    GetAIBuddyPermissionProfileDetail,
    GetAIBuddyPermissionProfileWithRulesDetail,
    UpdateAIBuddyPermissionProfileParam,
)
from backend.plugin.ai_buddy.service.permission_service import ai_buddy_permission_service
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID

router = APIRouter()


@router.get('/all', summary='获取所有权限预设', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_permission_profiles(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetAIBuddyPermissionProfileDetail]]:
    data = await ai_buddy_permission_service.get_all(
        db=db,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取权限预设',
    dependencies=[
        DependsPagination,
        Depends(RequestPermission('ai:permission-profile:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_permission_profiles_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyPermissionProfileQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddyPermissionProfileDetail]]:
    page_data = await ai_buddy_permission_service.get_list(
        db=db,
        user_id=request.user.id,
        name=query.name,
        status=query.status,
        builtin=query.builtin,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=page_data)


@router.get(
    '/{pk}',
    summary='获取权限预设详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_permission_profile(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='权限预设 ID')],
) -> ResponseSchemaModel[GetAIBuddyPermissionProfileWithRulesDetail]:
    data = await ai_buddy_permission_service.get(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建系统权限预设',
    dependencies=[
        Depends(RequestPermission('ai:permission-profile:add')),
        DependsRBAC,
    ],
)
async def create_ai_buddy_permission_profile(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyPermissionProfileParam,
) -> ResponseModel:
    await ai_buddy_permission_service.create(
        db=db,
        obj=obj,
        user_id=SYSTEM_OWNER_USER_ID,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success()


@router.post('/me', summary='创建我的权限预设', dependencies=[DependsJwtAuth])
async def create_my_ai_buddy_permission_profile(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyPermissionProfileParam,
) -> ResponseModel:
    await ai_buddy_permission_service.create(
        db=db,
        obj=obj,
        user_id=request.user.id,
        is_superuser=False,
    )
    return response_base.success()


@router.post('/{pk}/copy', summary='复制权限预设', dependencies=[DependsJwtAuth])
async def copy_ai_buddy_permission_profile(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='源权限预设 ID')],
    obj: CopyAIBuddyPermissionProfileParam,
) -> ResponseModel:
    await ai_buddy_permission_service.copy(
        db=db,
        pk=pk,
        obj=obj,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success()


@router.put(
    '/me/{pk}',
    summary='更新我的权限预设',
    dependencies=[DependsJwtAuth],
)
async def update_my_ai_buddy_permission_profile(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='权限预设 ID')],
    obj: UpdateAIBuddyPermissionProfileParam,
) -> ResponseModel:
    count = await ai_buddy_permission_service.update(
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
    summary='更新权限预设',
    dependencies=[
        Depends(RequestPermission('ai:permission-profile:edit')),
        DependsRBAC,
    ],
)
async def update_ai_buddy_permission_profile(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='权限预设 ID')],
    obj: UpdateAIBuddyPermissionProfileParam,
) -> ResponseModel:
    count = await ai_buddy_permission_service.update(
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
    summary='删除我的权限预设',
    dependencies=[DependsJwtAuth],
)
async def delete_my_ai_buddy_permission_profile(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='权限预设 ID')],
) -> ResponseModel:
    count = await ai_buddy_permission_service.delete(
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
    summary='删除权限预设',
    dependencies=[
        Depends(RequestPermission('ai:permission-profile:del')),
        DependsRBAC,
    ],
)
async def delete_ai_buddy_permission_profile(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='权限预设 ID')],
) -> ResponseModel:
    count = await ai_buddy_permission_service.delete(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
