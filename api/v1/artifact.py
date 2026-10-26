from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Path, Query, Request, Response

from backend.common.pagination import CursorPageData, DependsCursorPagination
from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.artifact import (
    AIBuddyArtifactQueryParam,
    GetAIBuddyArtifactDetail,
    GetAIBuddyArtifactListDetail,
    RegisterAIBuddyArtifactParam,
)
from backend.plugin.ai_buddy.service.artifact_service import ai_buddy_artifact_service

router = APIRouter()


@router.get('/all', summary='获取所有产物', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_artifacts(
    request: Request, db: CurrentSession
) -> ResponseSchemaModel[list[GetAIBuddyArtifactDetail]]:
    data = await ai_buddy_artifact_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '',
    summary='按类型游标查询产物',
    description='按产物 ID 倒序返回当前用户的产物元数据，正文通过详情或下载接口获取；续页需保持相同筛选条件',
    dependencies=[DependsJwtAuth, DependsCursorPagination],
)
async def get_ai_buddy_artifacts_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyArtifactQueryParam, Query()],
) -> ResponseSchemaModel[CursorPageData[GetAIBuddyArtifactListDetail]]:
    data = await ai_buddy_artifact_service.get_list(db=db, user_id=request.user.id, kind=query.kind)
    return response_base.success(data=data)


@router.get('/{pk}/content', summary='下载产物文件', dependencies=[DependsJwtAuth])
async def download_ai_buddy_artifact(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='产物 ID')],
) -> Response:
    data, filename, mime_type = await ai_buddy_artifact_service.download(db=db, pk=pk, user_id=request.user.id)
    return Response(
        content=data,
        media_type=mime_type,
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'private, no-store',
        },
    )


@router.post(
    '/workspace-reference',
    summary='注册工作区产物引用',
    dependencies=[DependsJwtAuth],
)
async def register_ai_buddy_artifact_reference(
    request: Request,
    db: CurrentSessionTransaction,
    obj: RegisterAIBuddyArtifactParam,
) -> ResponseSchemaModel[GetAIBuddyArtifactDetail]:
    data = await ai_buddy_artifact_service.register_reference(db=db, user_id=request.user.id, obj=obj)
    return response_base.success(data=data)


@router.get('/{pk}', summary='获取产物详情', dependencies=[DependsJwtAuth])
async def get_ai_buddy_artifact(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='产物 ID')],
) -> ResponseSchemaModel[GetAIBuddyArtifactDetail]:
    data = await ai_buddy_artifact_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)
