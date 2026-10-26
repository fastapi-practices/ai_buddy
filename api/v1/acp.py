from fastapi import APIRouter, Request, WebSocket

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.plugin.ai_buddy.agent.coding.protocol.acp.bridge import create_bridge, serve_bridge
from backend.plugin.ai_buddy.enums import AIBuddyAcpRunnerName
from backend.plugin.ai_buddy.schema.acp import (
    CheckAIBuddyAcpParam,
    CreateAIBuddyAcpBridgeParam,
    GetAIBuddyAcpBridgeDetail,
    GetAIBuddyAcpCheckDetail,
)
from backend.plugin.ai_buddy.service.acp_service import ai_buddy_acp_service

router = APIRouter()


@router.post('/{runner}/check', summary='检测 ACP Agent 连接', dependencies=[DependsJwtAuth])
async def check_ai_buddy_acp(
    request: Request, runner: AIBuddyAcpRunnerName, obj: CheckAIBuddyAcpParam
) -> ResponseSchemaModel[GetAIBuddyAcpCheckDetail]:
    data = await ai_buddy_acp_service.check(user_id=request.user.id, runner=runner, obj=obj)
    return response_base.success(data=data)


@router.post('/bridges', summary='登记桌面端本地 ACP 连接', dependencies=[DependsJwtAuth])
async def create_ai_buddy_acp_bridge(
    request: Request, obj: CreateAIBuddyAcpBridgeParam
) -> ResponseSchemaModel[GetAIBuddyAcpBridgeDetail]:
    data = await create_bridge(user_id=request.user.id, runner=obj.runner, cwd=obj.cwd)
    return response_base.success(data=data)


@router.websocket('/bridges/{bridge_id}')
async def connect_ai_buddy_acp_bridge(websocket: WebSocket, bridge_id: str) -> None:
    await serve_bridge(websocket, bridge_id)
