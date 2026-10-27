from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.ai_buddy.agent.work.input_requests import list_input_requests, resolve_input_request
from backend.plugin.ai_buddy.schema.input_request import GetAIBuddyInputRequestsDetail, ResolveAIBuddyInputRequestParam
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service


class AIBuddyInputRequestService:
    """校验会话归属后操作当前运行的输入请求"""

    @staticmethod
    async def get_list(
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
    ) -> GetAIBuddyInputRequestsDetail:
        """
        获取所属会话的运行输入请求

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :return:
        """
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=conversation_id, user_id=user_id
        )
        return GetAIBuddyInputRequestsDetail(items=await list_input_requests(conversation_id=conversation_id))

    @staticmethod
    async def resolve(
        *,
        db: AsyncSession,
        conversation_id: str,
        user_id: int,
        request_id: str,
        obj: ResolveAIBuddyInputRequestParam,
    ) -> None:
        """
        提交所属会话的运行输入答复

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param request_id: 输入请求 ID
        :param obj: 输入请求答复参数
        :return:
        """
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=conversation_id, user_id=user_id
        )
        await resolve_input_request(conversation_id=conversation_id, request_id=request_id, obj=obj)


ai_buddy_input_request_service = AIBuddyInputRequestService()
