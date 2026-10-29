from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Query, Request, UploadFile

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.model.skill import SYSTEM_SKILL_USER_ID
from backend.plugin.ai_buddy.schema.skill import (
    AIBuddySkillQueryParam,
    AIBuddySkillSearchQueryParam,
    GetAIBuddySkillDetail,
    GetAIBuddySkillSearchDetail,
)
from backend.plugin.ai_buddy.service.skill_service import ai_buddy_skill_service

router = APIRouter()


@router.get('/all', summary='获取所有技能', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_skills(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetAIBuddySkillDetail]]:
    data = await ai_buddy_skill_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取所有技能',
    dependencies=[
        DependsPagination,
        Depends(RequestPermission('ai:skill:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_skills_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddySkillQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddySkillDetail]]:
    page_data = await ai_buddy_skill_service.get_list(
        db=db,
        user_id=request.user.id,
        name=query.name,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=page_data)


@router.get('/search', summary='搜索技能', dependencies=[DependsJwtAuth])
async def search_ai_buddy_skills(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddySkillSearchQueryParam, Query()],
) -> ResponseSchemaModel[list[GetAIBuddySkillSearchDetail]]:
    data = await ai_buddy_skill_service.search(db=db, user_id=request.user.id, query=query.q)
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取技能详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_skill(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='技能 ID')],
) -> ResponseSchemaModel[GetAIBuddySkillDetail]:
    data = await ai_buddy_skill_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='上传内置技能',
    dependencies=[
        Depends(RequestPermission('ai:skill:add')),
        DependsRBAC,
    ],
)
async def create_ai_buddy_skill(
    db: CurrentSessionTransaction,
    file: Annotated[list[UploadFile], File(description='技能目录或包含技能目录的 zip')],
) -> ResponseModel:
    await ai_buddy_skill_service.create(db=db, user_id=SYSTEM_SKILL_USER_ID, files=file)
    return response_base.success()


@router.post(
    '/me',
    summary='上传我的技能',
    dependencies=[DependsJwtAuth],
)
async def create_my_ai_buddy_skill(
    request: Request,
    db: CurrentSessionTransaction,
    file: Annotated[list[UploadFile], File(description='技能目录或包含技能目录的 zip')],
) -> ResponseModel:
    await ai_buddy_skill_service.create(db=db, user_id=request.user.id, files=file)
    return response_base.success()


@router.delete(
    '/me/{pk}',
    summary='删除我的技能',
    dependencies=[DependsJwtAuth],
)
async def delete_my_ai_buddy_skill(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='技能 ID')],
) -> ResponseModel:
    count = await ai_buddy_skill_service.delete(
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
    summary='删除技能',
    dependencies=[
        Depends(RequestPermission('ai:skill:del')),
        DependsRBAC,
    ],
)
async def delete_ai_buddy_skill(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='技能 ID')],
) -> ResponseModel:
    count = await ai_buddy_skill_service.delete(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
