from typing import Annotated

from fastapi import APIRouter, Query, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.slash import (
    AIBuddySlashQueryParam,
    CreateAIBuddySlashParam,
    GetAIBuddySlashCommandDetail,
    GetAIBuddySlashResultDetail,
)
from backend.plugin.ai_buddy.service.slash_service import ai_buddy_slash_service

router = APIRouter()


@router.get('', summary='获取斜杠指令目录', dependencies=[DependsJwtAuth])
async def get_ai_buddy_slash_commands(
    query: Annotated[AIBuddySlashQueryParam, Query()],
) -> ResponseSchemaModel[list[GetAIBuddySlashCommandDetail]]:
    data = ai_buddy_slash_service.get_catalog(origin=query.origin)
    return response_base.success(data=data)


@router.post('', summary='执行斜杠指令', dependencies=[DependsJwtAuth])
async def execute_ai_buddy_slash_command(
    request: Request,
    db: CurrentSessionTransaction,
    obj: CreateAIBuddySlashParam,
) -> ResponseSchemaModel[GetAIBuddySlashResultDetail]:
    data = await ai_buddy_slash_service.execute(
        db=db,
        user_id=request.user.id,
        command=obj.command,
        origin=obj.origin,
        conversation_id=obj.conversation_id,
        args=obj.args,
        draft=obj.draft,
    )
    return response_base.success(data=data)
