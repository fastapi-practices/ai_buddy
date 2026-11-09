from backend.core.conf import settings

DURABILITY_AGENT_NAME = 'ai_buddy_work'
"""步骤持久化记录的 Agent 名，崩溃恢复按它定位运行"""


def durability_enabled(forwarded_props: object | None = None) -> bool:
    """
    解析容灾开关，服务端默认值为准，请求参数可显式覆盖

    :param forwarded_props: 本轮扩展参数
    :return:
    """
    default = bool(getattr(settings, 'AI_BUDDY_AGENT_DURABILITY_ENABLED', False))
    if forwarded_props is None:
        return default
    override = getattr(forwarded_props, 'durability_enabled', None)
    if override is None:
        return default
    return bool(override)


def durability_recovery_enabled() -> bool:
    """
    是否开启崩溃恢复后台任务

    :return:
    """
    return bool(getattr(settings, 'AI_BUDDY_AGENT_DURABILITY_RECOVERY_ENABLED', True))


def durability_recovery_interval_seconds() -> int:
    """
    崩溃恢复后台任务的扫描间隔

    :return:
    """
    return max(5, int(getattr(settings, 'AI_BUDDY_AGENT_DURABILITY_RECOVERY_INTERVAL_SECONDS', 60)))


def durability_stale_seconds() -> int:
    """
    助手消息静默多久判定为中断

    :return:
    """
    return max(30, int(getattr(settings, 'AI_BUDDY_AGENT_DURABILITY_STALE_SECONDS', 60)))
