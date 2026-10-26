from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.common.security.permission import RequestPermission
from backend.common.security.rbac import DependsRBAC
from backend.database.db import CurrentSession, CurrentSessionTransaction
from backend.plugin.ai_buddy.schema.mcp_oauth import (
    AIBuddyMcpOAuthCallbackQueryParam,
    GetAIBuddyMcpOauthAuthorizeDetail,
    GetAIBuddyMcpOauthConfigDetail,
    GetAIBuddyMcpOauthDetail,
    UpdateAIBuddyMcpOauthParam,
)
from backend.plugin.ai_buddy.service.mcp_oauth_service import ai_buddy_mcp_oauth_service

router = APIRouter()


@router.get('/oauth/callback', summary='接收 MCP OAuth 授权回调')
async def ai_buddy_mcp_oauth_callback(
    query: Annotated[AIBuddyMcpOAuthCallbackQueryParam, Query()],
) -> PlainTextResponse:
    await ai_buddy_mcp_oauth_service.callback(state=query.state, code=query.code, error=query.error)
    return PlainTextResponse('OAuth 已连接。请关闭此页面并返回 AI Buddy。', headers={'Cache-Control': 'no-store'})


@router.get('/{pk}/oauth', summary='获取 MCP OAuth 连接状态', dependencies=[DependsJwtAuth])
async def get_ai_buddy_mcp_oauth(
    request: Request, db: CurrentSession, pk: int
) -> ResponseSchemaModel[GetAIBuddyMcpOauthDetail]:
    data = await ai_buddy_mcp_oauth_service.get(db=db, user_id=request.user.id, mcp_id=pk)
    return response_base.success(data=data)


@router.get(
    '/{pk}/oauth/config',
    summary='获取平台 MCP OAuth 配置',
    dependencies=[Depends(RequestPermission('ai:mcp:query')), DependsRBAC],
)
async def get_ai_buddy_mcp_oauth_config(
    request: Request, db: CurrentSession, pk: int
) -> ResponseSchemaModel[GetAIBuddyMcpOauthConfigDetail]:
    data = await ai_buddy_mcp_oauth_service.get_config(
        db=db, user_id=request.user.id, mcp_id=pk, is_superuser=request.user.is_superuser
    )
    return response_base.success(data=data)


@router.put(
    '/{pk}/oauth/config',
    summary='配置平台 MCP OAuth 客户端',
    dependencies=[Depends(RequestPermission('ai:mcp:edit')), DependsRBAC],
)
async def update_ai_buddy_mcp_oauth_config(
    request: Request, db: CurrentSessionTransaction, pk: int, obj: UpdateAIBuddyMcpOauthParam
) -> ResponseModel:
    await ai_buddy_mcp_oauth_service.update_config(
        db=db, user_id=request.user.id, mcp_id=pk, obj=obj, is_superuser=request.user.is_superuser
    )
    return response_base.success()


@router.post('/{pk}/oauth/authorize', summary='开始 MCP OAuth 浏览器授权', dependencies=[DependsJwtAuth])
async def authorize_ai_buddy_mcp_oauth(
    request: Request, db: CurrentSessionTransaction, pk: int
) -> ResponseSchemaModel[GetAIBuddyMcpOauthAuthorizeDetail]:
    data = await ai_buddy_mcp_oauth_service.authorize(db=db, user_id=request.user.id, mcp_id=pk)
    return response_base.success(data=data)


@router.delete('/{pk}/oauth', summary='断开 MCP OAuth 连接', dependencies=[DependsJwtAuth])
async def disconnect_ai_buddy_mcp_oauth(request: Request, db: CurrentSessionTransaction, pk: int) -> ResponseModel:
    await ai_buddy_mcp_oauth_service.disconnect(db=db, user_id=request.user.id, mcp_id=pk)
    return response_base.success()
