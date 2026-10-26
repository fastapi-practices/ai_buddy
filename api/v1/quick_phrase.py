from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.model.quick_phrase import SYSTEM_QUICK_PHRASE_USER_ID
from backend.plugin.ai_buddy.schema.quick_phrase import (
    AIBuddyQuickPhraseQueryParam,
    CreateAIBuddyQuickPhraseParam,
    GetAIBuddyQuickPhraseDetail,
    UpdateAIBuddyQuickPhraseParam,
)
from backend.plugin.ai_buddy.service.quick_phrase_service import ai_buddy_quick_phrase_service

router = APIRouter()


@router.get('/all', summary='获取所有快捷短语', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_quick_phrases(
    request: Request, db: CurrentSession
) -> ResponseSchemaModel[list[GetAIBuddyQuickPhraseDetail]]:
    data = await ai_buddy_quick_phrase_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取所有快捷短语',
    dependencies=[
        DependsPagination,
        Depends(RequestPermission('ai:quick-phrase:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_quick_phrases_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyQuickPhraseQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddyQuickPhraseDetail]]:
    page_data = await ai_buddy_quick_phrase_service.get_list(
        db=db,
        user_id=request.user.id,
        content=query.content,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=page_data)


@router.get(
    '/{pk}',
    summary='获取快捷短语详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_quick_phrase(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='快捷短语 ID')],
) -> ResponseSchemaModel[GetAIBuddyQuickPhraseDetail]:
    data = await ai_buddy_quick_phrase_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建快捷短语',
    dependencies=[
        Depends(RequestPermission('ai:quick-phrase:add')),
        DependsRBAC,
    ],
)
async def create_ai_buddy_quick_phrase(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyQuickPhraseParam,
) -> ResponseModel:
    await ai_buddy_quick_phrase_service.create(db=db, obj=obj, user_id=SYSTEM_QUICK_PHRASE_USER_ID)
    return response_base.success()


@router.post(
    '/me',
    summary='创建我的快捷短语',
    dependencies=[DependsJwtAuth],
)
async def create_my_ai_buddy_quick_phrase(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyQuickPhraseParam,
) -> ResponseModel:
    await ai_buddy_quick_phrase_service.create(db=db, obj=obj, user_id=request.user.id)
    return response_base.success()


@router.put(
    '/me/{pk}',
    summary='更新我的快捷短语',
    dependencies=[DependsJwtAuth],
)
async def update_my_ai_buddy_quick_phrase(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='快捷短语 ID')],
    obj: UpdateAIBuddyQuickPhraseParam,
) -> ResponseModel:
    count = await ai_buddy_quick_phrase_service.update(
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
    summary='更新快捷短语',
    dependencies=[
        Depends(RequestPermission('ai:quick-phrase:edit')),
        DependsRBAC,
    ],
)
async def update_ai_buddy_quick_phrase(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='快捷短语 ID')],
    obj: UpdateAIBuddyQuickPhraseParam,
) -> ResponseModel:
    count = await ai_buddy_quick_phrase_service.update(
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
    summary='删除我的快捷短语',
    dependencies=[DependsJwtAuth],
)
async def delete_my_ai_buddy_quick_phrase(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='快捷短语 ID')],
) -> ResponseModel:
    count = await ai_buddy_quick_phrase_service.delete(
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
    summary='删除快捷短语',
    dependencies=[
        Depends(RequestPermission('ai:quick-phrase:del')),
        DependsRBAC,
    ],
)
async def delete_ai_buddy_quick_phrase(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='快捷短语 ID')],
) -> ResponseModel:
    count = await ai_buddy_quick_phrase_service.delete(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
