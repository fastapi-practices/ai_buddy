from typing import Annotated

from fastapi import APIRouter, Query, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession
from backend.plugin.ai_buddy.schema.approval_audit import (
    AIBuddyApprovalAuditQueryParam,
    GetAIBuddyApprovalAuditDetail,
)
from backend.plugin.ai_buddy.service.approval_audit_service import ai_buddy_approval_audit_service

router = APIRouter()


@router.get('', summary='获取当前用户的工具审批审计', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_approval_audits(
    request: Request,
    db: CurrentSession,
    query: Annotated[AIBuddyApprovalAuditQueryParam, Query()],
) -> ResponseSchemaModel[list[GetAIBuddyApprovalAuditDetail]]:
    data = await ai_buddy_approval_audit_service.get_all(
        db=db,
        user_id=request.user.id,
        before=query.before,
        limit=query.limit,
    )
    return response_base.success(data=data)
