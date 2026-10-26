from starlette.responses import StreamingResponse

from backend.plugin.ai_buddy.schema.image import AIBuddyImageCompletionParam
from backend.plugin.ai_buddy.service.chat_service import ai_buddy_chat_service


class AIBuddyImageService:
    """AI 生图服务类"""

    @staticmethod
    async def create_generation(
        *,
        user_id: int,
        obj: AIBuddyImageCompletionParam,
        accept: str | None,
    ) -> StreamingResponse:
        """
        创建流式生图

        :param user_id: 用户 ID
        :param obj: 请求体
        :param accept: Accept 请求头
        :return:
        """
        return await ai_buddy_chat_service.run_completion(
            user_id=user_id,
            run_input=obj,
            assistant_id=None,
            forwarded_props=obj.forwarded_props,
            accept=accept,
            empty_message_error='当前轮生图提示不能为空',
        )


ai_buddy_image_service: AIBuddyImageService = AIBuddyImageService()
