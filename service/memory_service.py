from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.work.memory_store import database_memory_store
from backend.plugin.ai_buddy.schema.memory import GetAIBuddyMemoryDetail, GetAIBuddyMemoryListDetail
from backend.plugin.ai_buddy.utils.memory_paths import memory_path_prefix

_LIST_LIMIT = 200
_PREVIEW_CHARS = 240
_DETAIL_CHARS = 20000


class AIBuddyMemoryService:
    """AI 记忆服务类"""

    @staticmethod
    async def get_all(*, user_id: int) -> list[GetAIBuddyMemoryListDetail]:
        """
        获取当前用户所有记忆

        :param user_id: 用户 ID
        :return:
        """
        store = database_memory_store
        paths = await store.list_paths(prefix=memory_path_prefix(user_id), limit=_LIST_LIMIT)
        items: list[GetAIBuddyMemoryListDetail] = []
        for path in paths:
            memory_file = await store.read(path, max_chars=_PREVIEW_CHARS)
            if memory_file is None:
                continue
            items.append(
                GetAIBuddyMemoryListDetail(
                    path=path,
                    truncated=memory_file.truncated,
                    preview=memory_file.content,
                )
            )
        return items

    @staticmethod
    async def get(*, user_id: int, path: str) -> GetAIBuddyMemoryDetail:
        """
        获取记忆详情

        :param user_id: 用户 ID
        :param path: 记忆路径
        :return:
        """
        normalized = path.strip().lstrip('/')
        prefix = memory_path_prefix(user_id)
        if not normalized or '..' in normalized.split('/') or not normalized.startswith(prefix):
            raise errors.RequestError(msg='记忆路径非法')
        store = database_memory_store
        memory_file = await store.read(normalized, max_chars=_DETAIL_CHARS)
        if memory_file is None:
            raise errors.NotFoundError(msg='记忆不存在')
        return GetAIBuddyMemoryDetail(
            path=normalized,
            content=memory_file.content,
            version=memory_file.version,
            truncated=memory_file.truncated,
        )

    async def delete(self, *, user_id: int, path: str) -> None:
        """
        删除记忆

        :param user_id: 用户 ID
        :param path: 记忆路径
        :return:
        """
        detail = await self.get(user_id=user_id, path=path)
        store = database_memory_store
        await store.delete(detail.path, expected_version=detail.version)


ai_buddy_memory_service: AIBuddyMemoryService = AIBuddyMemoryService()
