from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, File, Path, Query, Request, UploadFile
from starlette.responses import Response

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.workspace import (
    AIBuddyWorkspaceGarbageCollectParam,
    CreateAIBuddyWorkspaceParam,
    GetAIBuddyWorkspaceDetail,
    GetAIBuddyWorkspaceGarbageCollectDetail,
    UpdateAIBuddyWorkspaceParam,
)
from backend.plugin.ai_buddy.schema.workspace_file import (
    AIBuddyWorkspaceFileDeleteQueryParam,
    AIBuddyWorkspaceFileDownloadQueryParam,
    AIBuddyWorkspaceFileUploadQueryParam,
    GetAIBuddyWorkspaceFileDetail,
    UpsertAIBuddyWorkspaceFileParam,
)
from backend.plugin.ai_buddy.service.workspace_service import ai_buddy_workspace_service

router = APIRouter(dependencies=[DependsJwtAuth])


@router.get('/all', summary='获取所有工作区')
async def get_all_ai_buddy_workspaces(
    request: Request, db: CurrentSession
) -> ResponseSchemaModel[list[GetAIBuddyWorkspaceDetail]]:
    """获取当前用户所有工作区"""
    data = await ai_buddy_workspace_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get('/{workspace_id}', summary='获取工作区详情')
async def get_ai_buddy_workspace(
    request: Request,
    db: CurrentSession,
    workspace_id: Annotated[str, Path(max_length=128, description='工作区 ID')],
) -> ResponseSchemaModel[GetAIBuddyWorkspaceDetail]:
    """获取当前用户工作区详情"""
    data = await ai_buddy_workspace_service.get(db=db, user_id=request.user.id, workspace_id=workspace_id)
    return response_base.success(data=data)


@router.get('/{workspace_id}/files', summary='获取工作区文件清单')
async def get_ai_buddy_workspace_files(
    request: Request,
    db: CurrentSession,
    workspace_id: Annotated[str, Path(max_length=128, description='工作区 ID')],
) -> ResponseSchemaModel[list[GetAIBuddyWorkspaceFileDetail]]:
    """获取当前用户工作区文件清单"""
    data = await ai_buddy_workspace_service.get_files(db=db, user_id=request.user.id, workspace_id=workspace_id)
    return response_base.success(data=data)


@router.put('/{workspace_id}/files', summary='登记工作区文件清单')
async def upsert_ai_buddy_workspace_file(
    request: Request,
    db: CurrentSessionTransaction,
    workspace_id: Annotated[str, Path(max_length=128, description='工作区 ID')],
    obj: UpsertAIBuddyWorkspaceFileParam,
) -> ResponseSchemaModel[GetAIBuddyWorkspaceFileDetail]:
    """登记或更新当前用户工作区文件清单"""
    data = await ai_buddy_workspace_service.upsert_file(
        db=db,
        user_id=request.user.id,
        workspace_id=workspace_id,
        obj=obj,
    )
    return response_base.success(data=data)


@router.post('/{workspace_id}/files/content', summary='上传工作区文件字节')
async def upload_ai_buddy_workspace_file_content(
    request: Request,
    db: CurrentSessionTransaction,
    workspace_id: Annotated[str, Path(max_length=128, description='工作区 ID')],
    file: Annotated[UploadFile, File(description='工作区文件')],
    query: Annotated[AIBuddyWorkspaceFileUploadQueryParam, Query()],
) -> ResponseSchemaModel[GetAIBuddyWorkspaceFileDetail]:
    """上传工作区文件字节并更新文件清单"""
    data = await ai_buddy_workspace_service.upload_bytes(
        db=db,
        user_id=request.user.id,
        workspace_id=workspace_id,
        relative_path=query.relative_path,
        file=file,
        expected_revision=query.revision,
        expected_size=query.size,
        expected_sha256=query.sha256,
    )
    return response_base.success(data=data)


@router.get('/{workspace_id}/files/content', summary='下载工作区文件字节')
async def download_ai_buddy_workspace_file_content(
    request: Request,
    db: CurrentSession,
    workspace_id: Annotated[str, Path(max_length=128, description='工作区 ID')],
    query: Annotated[AIBuddyWorkspaceFileDownloadQueryParam, Query()],
) -> Response:
    """下载工作区文件字节并校验文件清单"""
    data, manifest = await ai_buddy_workspace_service.download_bytes(
        db=db,
        user_id=request.user.id,
        workspace_id=workspace_id,
        relative_path=query.relative_path,
        expected_revision=query.revision,
    )
    filename = manifest.relative_path.rsplit('/', 1)[-1]
    return Response(
        content=data,
        media_type=manifest.mime_type or 'application/octet-stream',
        headers={
            'Content-Disposition': f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            'X-AI-Buddy-Workspace-Revision': str(manifest.revision),
            'X-Content-Type-Options': 'nosniff',
            'Cache-Control': 'private, no-store',
        },
    )


@router.post('', summary='创建工作区')
async def create_ai_buddy_workspace(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyWorkspaceParam,
) -> ResponseSchemaModel[GetAIBuddyWorkspaceDetail]:
    """创建当前用户工作区"""
    data = await ai_buddy_workspace_service.create(db=db, user_id=request.user.id, obj=obj)
    return response_base.success(data=data)


@router.post('/{workspace_id}/garbage-collect', summary='预览或回收工作区未引用对象')
async def collect_ai_buddy_workspace_garbage(
    request: Request,
    db: CurrentSessionTransaction,
    workspace_id: Annotated[str, Path(max_length=128, description='工作区 ID')],
    obj: AIBuddyWorkspaceGarbageCollectParam,
) -> ResponseSchemaModel[GetAIBuddyWorkspaceGarbageCollectDetail]:
    """默认仅预览，确认后回收过期未引用对象"""
    data = await ai_buddy_workspace_service.collect_garbage(
        db=db, user_id=request.user.id, workspace_id=workspace_id, obj=obj
    )
    return response_base.success(data=data)


@router.put('/{workspace_id}', summary='更新工作区')
async def update_ai_buddy_workspace(
    request: Request,
    db: CurrentSessionTransaction,
    workspace_id: Annotated[str, Path(max_length=128, description='工作区 ID')],
    obj: UpdateAIBuddyWorkspaceParam,
) -> ResponseModel:
    """更新当前用户工作区"""
    count = await ai_buddy_workspace_service.update(
        db=db,
        user_id=request.user.id,
        workspace_id=workspace_id,
        obj=obj,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete('/{workspace_id}/files/content', summary='按版本删除工作区文件')
async def delete_ai_buddy_workspace_file_content(
    request: Request,
    db: CurrentSessionTransaction,
    workspace_id: Annotated[str, Path(max_length=128, description='工作区 ID')],
    query: Annotated[AIBuddyWorkspaceFileDeleteQueryParam, Query()],
) -> ResponseSchemaModel[GetAIBuddyWorkspaceFileDetail]:
    """显式删除文件清单并保留版本冲突保护"""
    data = await ai_buddy_workspace_service.delete_file(
        db=db,
        user_id=request.user.id,
        workspace_id=workspace_id,
        relative_path=query.relative_path,
        revision=query.revision,
    )
    return response_base.success(data=data)


@router.delete('/{workspace_id}', summary='删除工作区')
async def delete_ai_buddy_workspace(
    request: Request,
    db: CurrentSessionTransaction,
    workspace_id: Annotated[str, Path(max_length=128, description='工作区 ID')],
) -> ResponseModel:
    """删除当前用户工作区"""
    count = await ai_buddy_workspace_service.delete(db=db, user_id=request.user.id, workspace_id=workspace_id)
    if count > 0:
        return response_base.success()
    return response_base.fail()
