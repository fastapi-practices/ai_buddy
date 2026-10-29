from typing import Annotated

from fastapi import APIRouter, Path, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.object import (
    AIBuddyObjectGarbageCollectParam,
    GetAIBuddyObjectAuditDetail,
    GetAIBuddyObjectDetail,
    GetAIBuddyObjectEchoDetail,
    GetAIBuddyObjectGarbageCollectDetail,
)
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service

router = APIRouter()


@router.post(
    '/garbage-collect',
    summary='预览或回收当前用户已过宽限期的无引用对象',
    description='默认仅预览候选；dry_run 设为 false 才会物理删除，并为每个对象留下审计记录',
    dependencies=[DependsJwtAuth],
)
async def collect_ai_buddy_object_garbage(
    request: Request, db: CurrentSessionTransaction, obj: AIBuddyObjectGarbageCollectParam
) -> ResponseSchemaModel[GetAIBuddyObjectGarbageCollectDetail]:
    data = await ai_buddy_object_service.collect_garbage(db=db, user_id=request.user.id, obj=obj)
    return response_base.success(data=data)


@router.get('/{pk}', summary='获取统一对象详情', dependencies=[DependsJwtAuth])
async def get_ai_buddy_object(
    request: Request, db: CurrentSession, pk: Annotated[int, Path(description='对象 ID')]
) -> ResponseSchemaModel[GetAIBuddyObjectDetail]:
    data = await ai_buddy_object_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '/{pk}/echo',
    summary='回显统一对象',
    description='返回对象元数据和可用性，云端对象缺失、被删或存储不可用时给出可解释状态',
    dependencies=[DependsJwtAuth],
)
async def echo_ai_buddy_object(
    request: Request, db: CurrentSessionTransaction, pk: Annotated[int, Path(description='对象 ID')]
) -> ResponseSchemaModel[GetAIBuddyObjectEchoDetail]:
    data = await ai_buddy_object_service.echo(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.get('/{pk}/audits', summary='获取统一对象审计记录', dependencies=[DependsJwtAuth])
async def get_ai_buddy_object_audits(
    request: Request, db: CurrentSession, pk: Annotated[int, Path(description='对象 ID')]
) -> ResponseSchemaModel[list[GetAIBuddyObjectAuditDetail]]:
    data = await ai_buddy_object_service.get_audits(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)
