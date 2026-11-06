from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.ai_buddy.dataclasses import AIBuddyInvocationContext


class AIBuddyResourcePolicy:
    """AI 资源与调用策略基类"""

    @staticmethod
    async def before_invoke(*, db: AsyncSession, context: AIBuddyInvocationContext) -> None:
        """
        AI 调用前策略校验

        :param db: 数据库会话
        :param context: AI 调用策略上下文
        :return:
        """
        return
