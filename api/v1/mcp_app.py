from typing import Any

from fastapi import APIRouter, Request

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession
from backend.plugin.ai_buddy.schema.mcp_app import (
    AIBuddyMcpAppScope,
    CallAIBuddyMcpAppToolParam,
    GetAIBuddyMcpAppDetail,
    GetAIBuddyMcpAppToolInfo,
)
from backend.plugin.ai_buddy.service.mcp_app_service import ai_buddy_mcp_app_service

router = APIRouter()


@router.post(
    '/{conversation_id}/mcp-apps/resource', summary='读取当前会话的 MCP 应用资源', dependencies=[DependsJwtAuth]
)
async def read_ai_buddy_mcp_app_resource(
    request: Request, db: CurrentSession, conversation_id: str, obj: AIBuddyMcpAppScope
) -> ResponseSchemaModel[GetAIBuddyMcpAppDetail]:
    data = await ai_buddy_mcp_app_service.read_resource(
        db=db,
        conversation_id=conversation_id,
        user_id=request.user.id,
        is_superuser=request.user.is_superuser,
        scope=obj,
    )
    return response_base.success(data=data)


@router.post(
    '/{conversation_id}/mcp-apps/tool-info', summary='校验 MCP 应用工具与操作权限', dependencies=[DependsJwtAuth]
)
async def get_ai_buddy_mcp_app_tool_info(
    request: Request, db: CurrentSession, conversation_id: str, obj: CallAIBuddyMcpAppToolParam
) -> ResponseSchemaModel[GetAIBuddyMcpAppToolInfo]:
    data = await ai_buddy_mcp_app_service.tool_info(
        db=db, conversation_id=conversation_id, user_id=request.user.id, is_superuser=request.user.is_superuser, obj=obj
    )
    return response_base.success(data=data)


@router.post(
    '/{conversation_id}/mcp-apps/call-tool', summary='调用当前会话的 MCP 应用工具', dependencies=[DependsJwtAuth]
)
async def call_ai_buddy_mcp_app_tool(
    request: Request, db: CurrentSession, conversation_id: str, obj: CallAIBuddyMcpAppToolParam
) -> ResponseSchemaModel[dict[str, Any]]:
    data = await ai_buddy_mcp_app_service.call_tool(
        db=db, conversation_id=conversation_id, user_id=request.user.id, is_superuser=request.user.is_superuser, obj=obj
    )
    return response_base.success(data=data)
