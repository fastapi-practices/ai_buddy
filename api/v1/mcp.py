from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.mcp import (
    AIBuddyMcpQueryParam,
    CreateAIBuddyMcpParam,
    GetAIBuddyMcpDetail,
    ImportAIBuddyMcpParam,
    ImportAIBuddyMcpResult,
    UpdateAIBuddyMcpParam,
)
from backend.plugin.ai_buddy.service.mcp_service import ai_buddy_mcp_service
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID

router = APIRouter()


@router.get('/all', summary='获取所有 MCP', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_mcps(request: Request, db: CurrentSession) -> ResponseSchemaModel[list[GetAIBuddyMcpDetail]]:
    data = await ai_buddy_mcp_service.get_all(
        db=db,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取所有 MCP',
    dependencies=[
        DependsPagination,
        Depends(RequestPermission('ai:mcp:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_mcps_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyMcpQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddyMcpDetail]]:
    page_data = await ai_buddy_mcp_service.get_list(
        db=db,
        user_id=request.user.id,
        name=query.name,
        type=query.type,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=page_data)


@router.get(
    '/{pk}',
    summary='获取 MCP 详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_mcp(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='MCP ID')],
) -> ResponseSchemaModel[GetAIBuddyMcpDetail]:
    data = await ai_buddy_mcp_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建 MCP',
    dependencies=[
        Depends(RequestPermission('ai:mcp:add')),
        DependsRBAC,
    ],
)
async def create_ai_buddy_mcp(
    request: Request, db: CurrentSessionTransaction, obj: CreateAIBuddyMcpParam
) -> ResponseModel:
    await ai_buddy_mcp_service.create(
        db=db,
        obj=obj,
        user_id=SYSTEM_OWNER_USER_ID,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success()


@router.post(
    '/import',
    summary='导入内置 MCP JSON',
    dependencies=[
        Depends(RequestPermission('ai:mcp:add')),
        DependsRBAC,
    ],
)
async def import_ai_buddy_mcps(
    request: Request,
    db: CurrentSessionTransaction,
    obj: ImportAIBuddyMcpParam,
) -> ResponseSchemaModel[ImportAIBuddyMcpResult]:
    data = await ai_buddy_mcp_service.import_json(
        db=db,
        raw=obj.config,
        user_id=SYSTEM_OWNER_USER_ID,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=data)


@router.post(
    '/me',
    summary='创建我的 MCP',
    dependencies=[DependsJwtAuth],
)
async def create_my_ai_buddy_mcp(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyMcpParam,
) -> ResponseModel:
    await ai_buddy_mcp_service.create(
        db=db,
        obj=obj,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success()


@router.post(
    '/me/import',
    summary='导入我的 MCP JSON',
    dependencies=[DependsJwtAuth],
)
async def import_my_ai_buddy_mcps(
    request: Request,
    db: CurrentSessionTransaction,
    obj: ImportAIBuddyMcpParam,
) -> ResponseSchemaModel[ImportAIBuddyMcpResult]:
    data = await ai_buddy_mcp_service.import_json(
        db=db,
        raw=obj.config,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=data)


@router.put(
    '/me/{pk}',
    summary='更新我的 MCP',
    dependencies=[DependsJwtAuth],
)
async def update_my_ai_buddy_mcp(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='MCP ID')],
    obj: UpdateAIBuddyMcpParam,
) -> ResponseModel:
    count = await ai_buddy_mcp_service.update(
        db=db,
        pk=pk,
        obj=obj,
        user_id=request.user.id,
        is_superuser=False,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post(
    '/me/{pk}/clone',
    summary='复制内置 MCP 到我的',
    dependencies=[DependsJwtAuth],
)
async def clone_my_ai_buddy_mcp(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='MCP ID')],
) -> ResponseModel:
    await ai_buddy_mcp_service.clone_mine(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新 MCP',
    dependencies=[
        Depends(RequestPermission('ai:mcp:edit')),
        DependsRBAC,
    ],
)
async def update_ai_buddy_mcp(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='MCP ID')],
    obj: UpdateAIBuddyMcpParam,
) -> ResponseModel:
    count = await ai_buddy_mcp_service.update(
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
    summary='删除我的 MCP',
    dependencies=[DependsJwtAuth],
)
async def delete_my_ai_buddy_mcp(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='MCP ID')],
) -> ResponseModel:
    count = await ai_buddy_mcp_service.delete(
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
    summary='删除 MCP',
    dependencies=[
        Depends(RequestPermission('ai:mcp:del')),
        DependsRBAC,
    ],
)
async def delete_ai_buddy_mcp(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='MCP ID')],
) -> ResponseModel:
    count = await ai_buddy_mcp_service.delete(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
