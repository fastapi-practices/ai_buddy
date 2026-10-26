from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.ai_buddy.crud.crud_step_event import ai_buddy_step_event_dao
from backend.plugin.ai_buddy.crud.crud_step_run import ai_buddy_step_run_dao
from backend.plugin.ai_buddy.crud.crud_step_snapshot import ai_buddy_step_snapshot_dao
from backend.plugin.ai_buddy.crud.crud_step_tool_effect import ai_buddy_step_tool_effect_dao


class AIBuddyStepService:
    """AI 步骤持久化服务类"""

    @staticmethod
    async def delete_by_conversation(*, db: AsyncSession, conversation_id: str) -> int:
        """
        删除对话下的步骤事件、快照、工具台账和运行记录，这些都是可重新生成的派生数据

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        run_ids = await ai_buddy_step_run_dao.get_run_ids(db, conversation_id)
        await ai_buddy_step_event_dao.delete_by_run_ids(db, run_ids)
        await ai_buddy_step_snapshot_dao.delete_by_run_ids(db, run_ids)
        await ai_buddy_step_tool_effect_dao.delete_by_run_ids(db, run_ids)
        return await ai_buddy_step_run_dao.delete_by_conversation_id(db, conversation_id)


ai_buddy_step_service: AIBuddyStepService = AIBuddyStepService()
