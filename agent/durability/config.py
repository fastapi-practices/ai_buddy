from backend.core.conf import settings

DURABILITY_AGENT_NAME = 'ai_buddy_work'
"""步骤持久化记录的 Agent 名，崩溃恢复按它定位运行"""


def durability_enabled(forwarded_props: object | None = None) -> bool:
    """
    解析容灾开关，服务端默认值为准，请求参数可显式覆盖

    :param forwarded_props: 本轮扩展参数
    :return:
    """
    default = bool(settings.AI_BUDDY_AGENT_DURABILITY_ENABLED)
    if forwarded_props is None:
        return default
    override = getattr(forwarded_props, 'durability_enabled', None)
    if override is None:
        return default
    return bool(override)


def step_persistence_enabled(forwarded_props: object | None = None) -> bool:
    """
    步骤持久化是否启用，容灾执行会强制开启，历史检索依赖它落库

    :param forwarded_props: 本轮扩展参数
    :return:
    """
    return bool(settings.AI_BUDDY_AGENT_STEP_PERSISTENCE_ENABLED) or durability_enabled(forwarded_props)


def durability_recovery_enabled() -> bool:
    """
    是否开启崩溃恢复后台任务

    :return:
    """
    return bool(settings.AI_BUDDY_AGENT_DURABILITY_RECOVERY_ENABLED)


def durability_recovery_interval_seconds() -> int:
    """
    崩溃恢复后台任务的扫描间隔

    :return:
    """
    return max(5, int(settings.AI_BUDDY_AGENT_DURABILITY_RECOVERY_INTERVAL_SECONDS))


def durability_stale_seconds() -> int:
    """
    助手消息静默多久判定为中断

    :return:
    """
    return max(30, int(settings.AI_BUDDY_AGENT_DURABILITY_STALE_SECONDS))
