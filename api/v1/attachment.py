from typing import Annotated

from fastapi import APIRouter, File, Path, Request, UploadFile

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.attachment import (
    GetAIBuddyAttachmentDetail,
    PromoteAIBuddyAttachmentParam,
    StageAIBuddyAttachmentUrlParam,
)
from backend.plugin.ai_buddy.schema.object import GetAIBuddyObjectDetail
from backend.plugin.ai_buddy.service.attachment_service import ai_buddy_attachment_service

router = APIRouter()


@router.post(
    '/staged',
    summary='上传附件到暂存区',
    description='附件先进入暂存区，超过暂存期仍未被对话引用会被回收；被对话引用后才成为正式附件',
    dependencies=[DependsJwtAuth],
)
async def stage_ai_buddy_attachment(
    request: Request,
    db: CurrentSessionTransaction,
    file: Annotated[UploadFile, File(description='附件文件')],
) -> ResponseSchemaModel[GetAIBuddyAttachmentDetail]:
    data = await ai_buddy_attachment_service.stage_upload(db=db, user_id=request.user.id, file=file)
    return response_base.success(data=data)


@router.post(
    '/staged/from-url',
    summary='从远程地址下载附件到暂存区',
    description='只允许公网 http/https 地址，拦截内网、回环和重定向绕过，并限制文件大小与类型',
    dependencies=[DependsJwtAuth],
)
async def stage_ai_buddy_attachment_from_url(
    request: Request, db: CurrentSessionTransaction, obj: StageAIBuddyAttachmentUrlParam
) -> ResponseSchemaModel[GetAIBuddyAttachmentDetail]:
    data = await ai_buddy_attachment_service.stage_from_url(db=db, user_id=request.user.id, url=obj.url)
    return response_base.success(data=data)


@router.post('/staged/{pk}/promote', summary='提升暂存附件', dependencies=[DependsJwtAuth])
async def promote_ai_buddy_attachment(
    request: Request,
    db: CurrentSessionTransaction,
    pk: Annotated[int, Path(description='暂存对象 ID')],
    obj: PromoteAIBuddyAttachmentParam,
) -> ResponseSchemaModel[GetAIBuddyObjectDetail]:
    data = await ai_buddy_attachment_service.promote(
        db=db, user_id=request.user.id, pk=pk, conversation_id=obj.conversation_id
    )
    return response_base.success(data=data)
