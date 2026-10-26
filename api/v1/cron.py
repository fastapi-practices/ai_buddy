from typing import Annotated

from fastapi import APIRouter, Path, Request

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.cron import CreateAIBuddyCronParam, GetAIBuddyCronDetail, UpdateAIBuddyCronParam
from backend.plugin.ai_buddy.service.cron_service import ai_buddy_cron_service

router = APIRouter()


@router.get('/all', summary='获取所有定时任务', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_crons(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetAIBuddyCronDetail]]:
    data = await ai_buddy_cron_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '/{pk}',
    summary='获取定时任务详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_cron(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='任务 ID')],
) -> ResponseSchemaModel[GetAIBuddyCronDetail]:
    data = await ai_buddy_cron_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建定时任务',
    dependencies=[DependsJwtAuth],
)
async def create_ai_buddy_cron(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyCronParam,
) -> ResponseModel:
    await ai_buddy_cron_service.create(db=db, obj=obj, user_id=request.user.id)
    return response_base.success()


@router.put(
    '/{pk}',
    summary='更新定时任务',
    dependencies=[DependsJwtAuth],
)
async def update_ai_buddy_cron(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='任务 ID')],
    obj: UpdateAIBuddyCronParam,
) -> ResponseModel:
    count = await ai_buddy_cron_service.update(db=db, pk=pk, obj=obj, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.post(
    '/{pk}/run-now',
    summary='立即执行定时任务',
    dependencies=[DependsJwtAuth],
)
async def run_ai_buddy_cron_now(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='任务 ID')],
) -> ResponseModel:
    await ai_buddy_cron_service.run_now(db=db, pk=pk, user_id=request.user.id)
    return response_base.success()


@router.delete(
    '/{pk}',
    summary='删除定时任务',
    dependencies=[DependsJwtAuth],
)
async def delete_ai_buddy_cron(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='任务 ID')],
) -> ResponseModel:
    count = await ai_buddy_cron_service.delete(db=db, pk=pk, user_id=request.user.id)
    if count > 0:
        return response_base.success()
    return response_base.fail()
