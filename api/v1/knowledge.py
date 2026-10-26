from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, UploadFile

from backend.common.pagination import DependsPagination, PageData
from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.knowledge import (
    AIBuddyKnowledgeDocumentAllQueryParam,
    AIBuddyKnowledgeDocumentQueryParam,
    GetAIBuddyKnowledgeDetail,
)
from backend.plugin.ai_buddy.service.knowledge_service import ai_buddy_knowledge_service

router = APIRouter()


@router.get('/{pk}/documents/all', summary='获取知识库全部文档', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_knowledge_documents(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='知识库 ID')],
    query: Annotated[AIBuddyKnowledgeDocumentAllQueryParam, Query()],
) -> ResponseSchemaModel[list[GetAIBuddyKnowledgeDetail]]:
    data = await ai_buddy_knowledge_service.get_all(
        db=db,
        knowledge_base_id=pk,
        user_id=request.user.id,
        include_content=query.include_content,
    )
    return response_base.success(data=data)


@router.get(
    '/{pk}/documents',
    summary='分页获取知识库文档',
    dependencies=[DependsPagination, DependsJwtAuth],
)
async def get_ai_buddy_knowledge_documents_paginated(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='知识库 ID')],
    query: Annotated[AIBuddyKnowledgeDocumentQueryParam, Query()],
) -> ResponseSchemaModel[PageData[GetAIBuddyKnowledgeDetail]]:
    page_data = await ai_buddy_knowledge_service.get_list(
        db=db,
        title=query.title,
        knowledge_base_id=pk,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
        include_content=query.include_content,
    )
    return response_base.success(data=page_data)


@router.get(
    '/{pk}/documents/{doc_id}',
    summary='获取知识文档详情',
    dependencies=[DependsJwtAuth],
)
async def get_ai_buddy_knowledge_document(
    request: Request,
    db: CurrentSession,
    pk: Annotated[int, Path(description='知识库 ID')],
    doc_id: Annotated[int, Path(description='知识文档 ID')],
) -> ResponseSchemaModel[GetAIBuddyKnowledgeDetail]:
    data = await ai_buddy_knowledge_service.get(db=db, pk=doc_id, user_id=request.user.id, knowledge_base_id=pk)
    return response_base.success(data=data)


@router.post(
    '/{pk}/documents',
    summary='上传知识文档',
    dependencies=[
        Depends(RequestPermission('ai:knowledge:add')),
        DependsRBAC,
    ],
)
async def create_ai_buddy_knowledge_document(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='知识库 ID')],
    file: Annotated[list[UploadFile], File(description='知识文件、目录或 zip')],
    title: Annotated[str | None, Form(description='知识标题，仅单个文件时生效，空值使用文件名')] = None,
    provider_id: Annotated[int | None, Form(description='向量化供应商 ID，空则使用知识库配置')] = None,
    model_id: Annotated[str | None, Form(description='向量化模型 ID，空则使用知识库配置')] = None,
) -> ResponseModel:
    await ai_buddy_knowledge_service.create(
        db=db,
        user_id=request.user.id,
        files=file,
        knowledge_base_id=pk,
        title=title,
        provider_id=provider_id,
        model_id=model_id,
        is_superuser=request.user.is_superuser,
        allow_system=True,
    )
    return response_base.success()


@router.post(
    '/me/{pk}/documents',
    summary='上传我的知识文档',
    dependencies=[DependsJwtAuth],
)
async def create_my_ai_buddy_knowledge_document(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='知识库 ID')],
    file: Annotated[list[UploadFile], File(description='知识文件、目录或 zip')],
    title: Annotated[str | None, Form(description='知识标题，仅单个文件时生效，空值使用文件名')] = None,
    provider_id: Annotated[int | None, Form(description='向量化供应商 ID，空则使用知识库配置')] = None,
    model_id: Annotated[str | None, Form(description='向量化模型 ID，空则使用知识库配置')] = None,
) -> ResponseModel:
    await ai_buddy_knowledge_service.create(
        db=db,
        user_id=request.user.id,
        files=file,
        knowledge_base_id=pk,
        title=title,
        provider_id=provider_id,
        model_id=model_id,
        is_superuser=False,
        allow_system=False,
    )
    return response_base.success()


@router.delete(
    '/me/{pk}/documents/{doc_id}',
    summary='删除我的知识文档',
    dependencies=[DependsJwtAuth],
)
async def delete_my_ai_buddy_knowledge_document(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='知识库 ID')],
    doc_id: Annotated[int, Path(description='知识文档 ID')],
) -> ResponseModel:
    count = await ai_buddy_knowledge_service.delete(
        db=db,
        pk=doc_id,
        user_id=request.user.id,
        is_superuser=False,
        allow_system=False,
        knowledge_base_id=pk,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()


@router.delete(
    '/{pk}/documents/{doc_id}',
    summary='删除知识文档',
    dependencies=[
        Depends(RequestPermission('ai:knowledge:del')),
        DependsRBAC,
    ],
)
async def delete_ai_buddy_knowledge_document(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='知识库 ID')],
    doc_id: Annotated[int, Path(description='知识文档 ID')],
) -> ResponseModel:
    count = await ai_buddy_knowledge_service.delete(
        db=db,
        pk=doc_id,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
        allow_system=True,
        knowledge_base_id=pk,
    )
    if count > 0:
        return response_base.success()
    return response_base.fail()
