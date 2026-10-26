from typing import Annotated

from fastapi import APIRouter, Path, Request

from backend.common.response.response_schema import ResponseModel, ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.plugin.ai_buddy.schema.memory import GetAIBuddyMemoryDetail, GetAIBuddyMemoryListDetail
from backend.plugin.ai_buddy.service.memory_service import ai_buddy_memory_service

router = APIRouter()


@router.get('/all', summary='获取所有记忆', dependencies=[DependsJwtAuth])
async def get_all_ai_buddy_memories(request: Request) -> ResponseSchemaModel[list[GetAIBuddyMemoryListDetail]]:
    data = await ai_buddy_memory_service.get_all(user_id=request.user.id)
    return response_base.success(data=data)


@router.get('/{path:path}', summary='获取记忆详情', dependencies=[DependsJwtAuth])
async def get_ai_buddy_memory(
    request: Request,
    path: Annotated[str, Path(description='记忆路径')],
) -> ResponseSchemaModel[GetAIBuddyMemoryDetail]:
    data = await ai_buddy_memory_service.get(user_id=request.user.id, path=path)
    return response_base.success(data=data)


@router.delete('/{path:path}', summary='删除记忆', dependencies=[DependsJwtAuth])
async def delete_ai_buddy_memory(
    request: Request,
    path: Annotated[str, Path(description='记忆路径')],
) -> ResponseModel:
    await ai_buddy_memory_service.delete(user_id=request.user.id, path=path)
    return response_base.success()
