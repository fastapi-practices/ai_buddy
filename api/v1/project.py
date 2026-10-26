from typing import Annotated

from fastapi import APIRouter, Path, Request

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.project import (
    CreateAIBuddyProjectParam,
    GetAIBuddyProjectDetail,
    UpdateAIBuddyProjectParam,
)
from backend.plugin.ai_buddy.service.project_service import ai_buddy_project_service

router = APIRouter()


@router.get('/all', summary='获取所有项目', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_projects(
    request: Request, db: CurrentSession
) -> ResponseSchemaModel[list[GetAIBuddyProjectDetail]]:
    data = await ai_buddy_project_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get('/{pk}', summary='获取项目详情', dependencies=[DependsJwtAuth])
async def get_ai_buddy_project(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='项目 ID')],
) -> ResponseSchemaModel[GetAIBuddyProjectDetail]:
    data = await ai_buddy_project_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post('', summary='创建项目', dependencies=[DependsJwtAuth])
async def create_ai_buddy_project(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyProjectParam,
) -> ResponseModel:
    await ai_buddy_project_service.create(db=db, user_id=request.user.id, obj=obj)
    return response_base.success()


@router.put('/{pk}', summary='更新项目', dependencies=[DependsJwtAuth])
async def update_ai_buddy_project(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='项目 ID')],
    obj: UpdateAIBuddyProjectParam,
) -> ResponseModel:
    count = await ai_buddy_project_service.update(db=db, pk=pk, user_id=request.user.id, obj=obj)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete('/{pk}', summary='删除项目', dependencies=[DependsJwtAuth])
async def delete_ai_buddy_project(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='项目 ID')],
) -> ResponseModel:
    count = await ai_buddy_project_service.delete(db=db, pk=pk, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()
