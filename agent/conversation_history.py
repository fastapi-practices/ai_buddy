from pydantic_ai.messages import ModelMessage
from pydantic_ai_harness.conversation_search import SnapshotHistorySource
from pydantic_ai_harness.step_persistence import RunRecord

from backend.plugin.ai_buddy.agent.step_store import AIBuddyStepStore


class BuddyConversationHistorySource:
    """按对话范围提供持久化历史，跨对话的运行记录不会进入检索语料"""

    def __init__(self, store: AIBuddyStepStore, *, conversation_id: str) -> None:
        """
        绑定步骤存储与对话范围

        :param store: 步骤存储
        :param conversation_id: 对话 ID
        :return:
        """
        self._store = store
        self._conversation_id = conversation_id
        self._source = SnapshotHistorySource(store)

    async def list_runs(self) -> list[RunRecord]:
        """
        列出当前对话的运行记录

        :return:
        """
        return await self._store.list_runs(conversation_id=self._conversation_id)

    async def run_history(self, *, run_id: str) -> list[ModelMessage]:
        """
        读取一个运行的持久化消息记录

        :param run_id: 运行 ID
        :return:
        """
        return await self._source.run_history(run_id=run_id)
