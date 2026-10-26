from backend.core.conf import settings


def resolve_run_timeout(requested: float | None) -> float:
    """
    解析本轮运行时限，未指定时使用默认值，指定值不能超过配置上限

    :param requested: 客户端请求的执行时限，单位秒
    :return:
    """
    cap = float(settings.AI_BUDDY_AGENT_RUN_TIMEOUT_SECONDS)
    return cap if requested is None else min(requested, cap)
