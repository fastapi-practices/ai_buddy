from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.knowledge_base import (
    AIBuddyKnowledgeBaseQueryParam,
    CreateAIBuddyKnowledgeBaseParam,
    GetAIBuddyKnowledgeBaseDetail,
    UpdateAIBuddyKnowledgeBaseParam,
)
from backend.plugin.ai_buddy.schema.onnx_option import (
    DownloadAIBuddyOnnxParam,
    GetAIBuddyOnnxCatalogDetail,
    GetAIBuddyOnnxDownloadStatusDetail,
)
from backend.plugin.ai_buddy.service.knowledge_base_service import ai_buddy_knowledge_base_service
from backend.plugin.ai_buddy.utils.ownership import SYSTEM_OWNER_USER_ID

router = APIRouter()


@router.get(
    '/onnx-options',
    summary='获取本地 ONNX 选项',
    description='获取本地向量和 OCR 模型选项',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_onnx_options() -> ResponseSchemaModel[GetAIBuddyOnnxCatalogDetail]:
    data = await ai_buddy_knowledge_base_service.get_onnx_options()
    return response_base.success(data=data)


@router.post('/onnx-download', summary='下载本地 ONNX 向量模型', dependencies=[DependsJwtAuth])
async def download_ai_buddy_onnx_model(
    obj: DownloadAIBuddyOnnxParam,
) -> ResponseSchemaModel[GetAIBuddyOnnxDownloadStatusDetail]:
    data = await ai_buddy_knowledge_base_service.download_onnx_model(model_id=obj.model_id)
    return response_base.success(data=data)


@router.get('/onnx-download-status', summary='获取 ONNX 向量模型下载状态', dependencies=[DependsJwtAuth])
async def get_ai_buddy_onnx_download_status() -> ResponseSchemaModel[GetAIBuddyOnnxDownloadStatusDetail]:
    data = await ai_buddy_knowledge_base_service.get_onnx_download_status()
    return response_base.success(data=data)


@router.post('/ocr-onnx-download', summary='下载本地 ONNX OCR 模型', dependencies=[DependsJwtAuth])
async def download_ai_buddy_ocr_onnx_model(
    obj: DownloadAIBuddyOnnxParam,
) -> ResponseSchemaModel[GetAIBuddyOnnxDownloadStatusDetail]:
    data = await ai_buddy_knowledge_base_service.download_ocr_onnx_model(model_id=obj.model_id)
    return response_base.success(data=data)


@router.get('/ocr-onnx-download-status', summary='获取 ONNX OCR 模型下载状态', dependencies=[DependsJwtAuth])
async def get_ai_buddy_ocr_onnx_download_status() -> ResponseSchemaModel[GetAIBuddyOnnxDownloadStatusDetail]:
    data = await ai_buddy_knowledge_base_service.get_ocr_onnx_download_status()
    return response_base.success(data=data)


@router.post('/paddleocr-download', summary='下载本机 PaddleOCR 模型', dependencies=[DependsJwtAuth])
async def download_ai_buddy_paddleocr_model(
    obj: DownloadAIBuddyOnnxParam,
) -> ResponseSchemaModel[GetAIBuddyOnnxDownloadStatusDetail]:
    data = await ai_buddy_knowledge_base_service.download_paddleocr_model(model_id=obj.model_id)
    return response_base.success(data=data)


@router.get('/paddleocr-download-status', summary='获取本机 PaddleOCR 模型下载状态', dependencies=[DependsJwtAuth])
async def get_ai_buddy_paddleocr_download_status() -> ResponseSchemaModel[GetAIBuddyOnnxDownloadStatusDetail]:
    data = await ai_buddy_knowledge_base_service.get_paddleocr_download_status()
    return response_base.success(data=data)


@router.get('/all', summary='获取所有知识库', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_knowledge_bases(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetAIBuddyKnowledgeBaseDetail]]:
    data = await ai_buddy_knowledge_base_service.get_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get('/me', summary='获取我的知识库', dependencies=[DependsJwtAuth])
async def get_my_ai_buddy_knowledge_bases(
    request: Request,
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetAIBuddyKnowledgeBaseDetail]]:
    data = await ai_buddy_knowledge_base_service.get_mine_all(db=db, user_id=request.user.id)
    return response_base.success(data=data)


@router.get(
    '',
    summary='分页获取所有知识库',
    dependencies=[
        DependsPagination,
        Depends(RequestPermission('ai:knowledge:list')),
        DependsRBAC,
    ],
)
async def get_ai_buddy_knowledge_bases_paginated(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyKnowledgeBaseQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddyKnowledgeBaseDetail]]:
    page_data = await ai_buddy_knowledge_base_service.get_list(
        db=db,
        user_id=request.user.id,
        name=query.name,
        is_superuser=request.user.is_superuser,
    )
    return response_base.success(data=page_data)


@router.get(
    '/{pk}',
    summary='获取知识库详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_knowledge_base(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='知识库 ID')],
) -> ResponseSchemaModel[GetAIBuddyKnowledgeBaseDetail]:
    data = await ai_buddy_knowledge_base_service.get(db=db, pk=pk, user_id=request.user.id)
    return response_base.success(data=data)


@router.post(
    '',
    summary='创建知识库',
    dependencies=[
        Depends(RequestPermission('ai:knowledge:add')),
        DependsRBAC,
    ],
)
async def create_ai_buddy_knowledge_base(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyKnowledgeBaseParam,
) -> ResponseModel:
    await ai_buddy_knowledge_base_service.create(db=db, user_id=SYSTEM_OWNER_USER_ID, obj=obj)
    return response_base.success()


@router.post(
    '/me',
    summary='创建我的知识库',
    dependencies=[DependsJwtAuth],
)
async def create_my_ai_buddy_knowledge_base(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddyKnowledgeBaseParam,
) -> ResponseSchemaModel[GetAIBuddyKnowledgeBaseDetail]:
    data = await ai_buddy_knowledge_base_service.create(db=db, user_id=request.user.id, obj=obj)
    return response_base.success(data=data)


@router.put(
    '/me/{pk}',
    summary='更新我的知识库',
    dependencies=[DependsJwtAuth],
)
async def update_my_ai_buddy_knowledge_base(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='知识库 ID')],
    obj: UpdateAIBuddyKnowledgeBaseParam,
) -> ResponseModel:
    count = await ai_buddy_knowledge_base_service.update(
        db=db,
        pk=pk,
        user_id=request.user.id,
        obj=obj,
        is_superuser=False,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.put(
    '/{pk}',
    summary='更新知识库',
    dependencies=[
        Depends(RequestPermission('ai:knowledge:edit')),
        DependsRBAC,
    ],
)
async def update_ai_buddy_knowledge_base(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='知识库 ID')],
    obj: UpdateAIBuddyKnowledgeBaseParam,
) -> ResponseModel:
    count = await ai_buddy_knowledge_base_service.update(
        db=db,
        pk=pk,
        user_id=request.user.id,
        obj=obj,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/me/{pk}',
    summary='删除我的知识库',
    dependencies=[DependsJwtAuth],
)
async def delete_my_ai_buddy_knowledge_base(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='知识库 ID')],
) -> ResponseModel:
    count = await ai_buddy_knowledge_base_service.delete(
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
    summary='删除知识库',
    dependencies=[
        Depends(RequestPermission('ai:knowledge:del')),
        DependsRBAC,
    ],
)
async def delete_ai_buddy_knowledge_base(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='知识库 ID')],
) -> ResponseModel:
    count = await ai_buddy_knowledge_base_service.delete(
        db=db,
        pk=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
