from fastapi import APIRouter

from backend.common.response.response_schema import ResponseSchemaModel, response_base
from backend.common.security.jwt import DependsJwtAuth
from backend.database.db import CurrentSession
from backend.plugin.ai_buddy.schema.web_search import GetAIBuddyWebSearchOptionDetail
from backend.plugin.ai_buddy.service.web_search_service import ai_buddy_web_search_service

router = APIRouter()


@router.get('', summary='获取联网搜索选项', dependencies=[DependsJwtAuth])
async def get_ai_buddy_web_search_options(
    db: CurrentSession,
) -> ResponseSchemaModel[list[GetAIBuddyWebSearchOptionDetail]]:
    data = await ai_buddy_web_search_service.get_all(db=db)
    return response_base.success(data=data)
