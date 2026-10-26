from typing import Annotated

from fastapi import APIRouter, Path, Request, WebSocket

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.core.conf import settings
from backend.database.db import CurrentSession
from backend.plugin.ai_buddy.agent.coding.execution_bridge import (
    close_owned_bridge,
    create_bridge,
    serve_bridge,
)
from backend.plugin.ai_buddy.enums import AIBuddyExecutionCapability
from backend.plugin.ai_buddy.schema.execution import (
    CreateAIBuddyExecutionBridgeParam,
    GetAIBuddyExecutionBridgeDetail,
    GetAIBuddyExecutionOptionsDetail,
)
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config

router = APIRouter()


@router.get('/options', summary='获取编码默认执行配置', dependencies=[DependsJwtAuth])
async def get_ai_buddy_execution_options(db: CurrentSession) -> ResponseSchemaModel[GetAIBuddyExecutionOptionsDetail]:
    await load_ai_buddy_config(db)
    return response_base.success(
        data={
            'default_backend': settings.AI_BUDDY_AGENT_EXECUTION_BACKEND,
            'capabilities': list(AIBuddyExecutionCapability),
        }
    )


@router.post('/bridges', summary='登记桌面端执行连接', dependencies=[DependsJwtAuth])
async def create_ai_buddy_execution_bridge(
    request: Request, obj: CreateAIBuddyExecutionBridgeParam
) -> ResponseSchemaModel[GetAIBuddyExecutionBridgeDetail]:
    data = await create_bridge(user_id=request.user.id, obj=obj)
    return response_base.success(data=data)


@router.delete('/bridges/{bridge_id}', summary='关闭当前用户的桌面执行连接', dependencies=[DependsJwtAuth])
async def close_ai_buddy_execution_bridge(
    request: Request, bridge_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$', description='桌面执行连接 ID')]
) -> ResponseModel:
    await close_owned_bridge(bridge_id=bridge_id, user_id=request.user.id)
    return response_base.success()


@router.websocket('/bridges/{bridge_id}')
async def connect_ai_buddy_execution_bridge(
    websocket: WebSocket, bridge_id: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')]
) -> None:
    await serve_bridge(websocket, bridge_id)
