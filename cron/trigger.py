import datetime as dt

from functools import lru_cache

from backend.app.task.utils.tzcrontab import TzAwareCrontab, crontab_verify
from backend.common.exception import errors
from backend.utils.timezone import timezone

_TRIGGER_KINDS = frozenset({'cron', 'interval', 'date'})


@lru_cache(maxsize=256)
def parse_cron(expr: str) -> TzAwareCrontab:
    """
    解析 5 段 Unix cron，与 task 应用一样使用 Celery 时区感知 crontab

    :param expr: Cron 表达式
    :return:
    """
    crontab_verify(expr)
    return TzAwareCrontab.from_string(expr)


def _with_default_timezone(run_date: dt.datetime) -> dt.datetime:
    """
    为调度时间补充默认时区

    :param run_date: 计划执行时间
    :return:
    """
    return run_date.replace(tzinfo=timezone.tz_info) if run_date.tzinfo is None else run_date


def parse_trigger(spec: str) -> tuple[str, str]:
    """
    解析 trigger 字符串，返回 kind 和 value

    :param spec: cron:<expr> / interval:<seconds> / date:<ISO>，或裸 5 段 cron
    :return:
    """
    text = spec.strip()
    if not text:
        raise errors.RequestError(msg='调度表达式不能为空')
    if ':' not in text:
        kind, value = 'cron', text
    else:
        kind, _, value = text.partition(':')
        value = value.strip()
    if kind not in _TRIGGER_KINDS:
        raise errors.RequestError(msg=f'不支持的调度类型: {kind}')
    if not value:
        raise errors.RequestError(msg='调度表达式不能为空')
    try:
        if kind == 'interval':
            seconds = int(value)
            if seconds <= 0:
                raise ValueError('间隔秒数必须大于 0')
            return kind, str(seconds)
        if kind == 'cron':
            expr = ' '.join(value.split())
            crontab_verify(expr)
            return kind, expr
        return kind, _with_default_timezone(dt.datetime.fromisoformat(value)).isoformat()
    except (ValueError, TypeError) as exc:
        raise errors.RequestError(msg=f'无法解析调度表达式: {exc}') from exc


def normalize_trigger(spec: str) -> str:
    """
    规范化并校验 trigger

    :param spec: 原始调度表达式
    :return:
    """
    kind, value = parse_trigger(spec)
    return f'{kind}:{value}'


def parse_date_trigger(value: str) -> dt.datetime:
    """
    解析一次性调度时间

    :param value: ISO 时间
    :return:
    """
    return timezone.from_datetime(_with_default_timezone(dt.datetime.fromisoformat(value)))
