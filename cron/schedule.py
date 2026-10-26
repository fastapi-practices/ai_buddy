from datetime import datetime, timedelta

from celery import schedules

from backend.common.exception import errors
from backend.plugin.ai_buddy.cron.trigger import parse_cron, parse_date_trigger, parse_trigger
from backend.utils.timezone import timezone


def trigger_is_due(
    spec: str,
    *,
    now: datetime,
    last_run_time: datetime | None,
    created_time: datetime | None,
) -> bool:
    """
    判断调度是否到期，cron 与 interval 和 task 应用一样交给 Celery schedule 判断

    :param spec: 调度表达式
    :param now: 当前时间
    :param last_run_time: 最近执行时间
    :param created_time: 创建时间
    :return:
    """
    try:
        kind, value = parse_trigger(spec)
    except errors.RequestError:
        return False
    anchor = last_run_time or created_time
    if kind == 'cron':
        return parse_cron(value).is_due(timezone.from_datetime(anchor or now))[0]
    if kind == 'interval':
        if anchor is None:
            return True
        return schedules.schedule(timedelta(seconds=int(value)), nowfun=timezone.now).is_due(
            timezone.from_datetime(anchor)
        )[0]
    return last_run_time is None and now >= parse_date_trigger(value)
