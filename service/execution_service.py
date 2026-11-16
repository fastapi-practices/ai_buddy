from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.coding.sandbox_runtime import sandbox_unavailable_reason
from backend.plugin.ai_buddy.enums import AIBuddyExecutionBackend, AIBuddyExecutionCapability
from backend.plugin.ai_buddy.schema.execution import GetAIBuddyExecutionOptionsDetail
from backend.plugin.ai_buddy.utils.dynamic_config import load_ai_buddy_config


class AIBuddyExecutionService:
    """AI 编码执行配置服务类"""

    @staticmethod
    async def get_options(*, db: AsyncSession) -> GetAIBuddyExecutionOptionsDetail:
        """
        获取客户端可用的执行后端与沙箱配置

        :param db: 数据库会话
        :return:
        """
        await load_ai_buddy_config(db)
        sandbox_reason = sandbox_unavailable_reason()
        sandbox_enabled = sandbox_reason is None
        default_backend = settings.AI_BUDDY_AGENT_EXECUTION_BACKEND
        if default_backend == AIBuddyExecutionBackend.sandbox and not sandbox_enabled:
            default_backend = AIBuddyExecutionBackend.local
        return GetAIBuddyExecutionOptionsDetail(
            default_backend=default_backend,
            sandbox_enabled=sandbox_enabled,
            sandbox_reason=sandbox_reason,
            capabilities=list(AIBuddyExecutionCapability),
        )


ai_buddy_execution_service: AIBuddyExecutionService = AIBuddyExecutionService()
