from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.plugin.ai_buddy.enums import AIBuddyWebSearchType
from backend.plugin.ai_buddy.schema.web_search import GetAIBuddyWebSearchOptionDetail
from backend.plugin.ai_buddy.utils.dynamic_config import get_ai_buddy_config_snapshot

_WEB_SEARCH_OPTIONS: tuple[tuple[AIBuddyWebSearchType, str, str | None], ...] = (
    (AIBuddyWebSearchType.builtin, '内置搜索', None),
    (AIBuddyWebSearchType.duckduckgo, 'DuckDuckGo', None),
    (AIBuddyWebSearchType.exa, 'Exa', 'AI_BUDDY_EXA_API_KEY'),
    (AIBuddyWebSearchType.tavily, 'Tavily', 'AI_BUDDY_TAVILY_API_KEY'),
)


class AIBuddyWebSearchService:
    """联网搜索选项服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession) -> list[GetAIBuddyWebSearchOptionDetail]:
        """
        获取联网搜索选项

        :param db: 数据库会话
        :return:
        """
        config_status, config_values = await get_ai_buddy_config_snapshot(db)
        options: list[GetAIBuddyWebSearchOptionDetail] = []
        for search_type, name, config_key in _WEB_SEARCH_OPTIONS:
            if config_key is None:
                status = StatusType.enable
                key_status = StatusType.enable
            else:
                status = config_status
                key_status = StatusType.enable if config_values.get(config_key, '').strip() else StatusType.disable
            options.append(
                GetAIBuddyWebSearchOptionDetail(
                    type=search_type,
                    name=name,
                    status=status,
                    key_status=key_status,
                )
            )
        return options


ai_buddy_web_search_service: AIBuddyWebSearchService = AIBuddyWebSearchService()
