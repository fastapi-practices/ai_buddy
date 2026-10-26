from typing import Any

from pydantic_ai.exceptions import (
    ModelConnectionError,
    ModelContextWindowExceededError,
    ModelQuotaExceededError,
    ModelRateLimitError,
    ModelRequestTimeout,
    ModelServerError,
    ModelTimeoutError,
    ModelUnavailableError,
    RunTimedOut,
)

_DEFAULT_ERROR_MESSAGE = '生成失败'
_MAX_BODY_CHARS = 8000


def _body_message(body: object) -> str | None:
    """
    从供应商响应体提取可读错误信息

    :param body: 响应体
    :return:
    """
    if not isinstance(body, dict):
        return None
    for key in ('message', 'msg', 'error'):
        value = body.get(key)
        candidate = value.get('message') if isinstance(value, dict) else value
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def build_run_error_payload(
    error: BaseException | str | None,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    从运行异常构建可展示的错误载荷

    :param error: 异常、事件或纯文本
    :param extra: 额外字段，例如协议事件 code
    :return:
    """
    payload: dict[str, Any] = {'message': _DEFAULT_ERROR_MESSAGE}
    if isinstance(error, str):
        text = error.strip() or _DEFAULT_ERROR_MESSAGE
        payload['message'] = text
        payload['reason'] = text
    elif isinstance(error, BaseException):
        payload['type'] = type(error).__qualname__
        payload['module'] = type(error).__module__
        payload['reason'] = str(error) or _DEFAULT_ERROR_MESSAGE
        payload['message'] = getattr(error, 'message', None) or payload['reason']
        payload.update({
            attr: value
            for attr in ('status_code', 'model_name', 'suggested_model_id', 'retry_after')
            if (value := getattr(error, attr, None)) is not None
        })
        body = getattr(error, 'body', None)
        if body is not None:
            payload['body'] = _jsonable(body)
        payload['message'] = _body_message(body) or payload['message']
        cause = error.__cause__ or error.__context__
        if isinstance(cause, BaseException) and cause is not error:
            payload['cause'] = {
                'type': type(cause).__qualname__,
                'message': str(cause) or type(cause).__qualname__,
            }
        for error_type, code, message, retryable in (
            (RunTimedOut, 'run_timeout', '本轮执行已达到时限，可调整执行时限后继续', False),
            (ModelRequestTimeout, 'model_request_timeout', '模型请求超过总时限，请稍后重试或调整时限', True),
            (ModelTimeoutError, 'model_timeout', '模型响应超时，请稍后重试', True),
            (ModelRateLimitError, 'model_rate_limit', '模型请求频率受限，请稍后重试', True),
            (ModelQuotaExceededError, 'model_quota_exceeded', '模型供应商额度不足，请检查余额或配额', False),
            (ModelContextWindowExceededError, 'model_context_exceeded', '模型上下文超限，请压缩历史或更换模型', False),
            (ModelUnavailableError, 'model_unavailable', '模型暂时不可用，请稍后重试', True),
            (ModelServerError, 'model_server_error', '模型供应商服务异常，请稍后重试', True),
            (ModelConnectionError, 'model_connection_error', '模型连接中断，请检查网络后重试', True),
        ):
            if isinstance(error, error_type):
                payload.update(code=code, message=message, retryable=retryable)
                break
    payload.update({key: value for key, value in (extra or {}).items() if value is not None and key not in payload})
    return payload


def _jsonable(value: object | None) -> object | None:
    """
    将错误详情转为可 JSON 序列化的结构

    :param value: 原始值
    :return:
    """
    if value is None:
        return None
    if isinstance(value, str | int | float | bool):
        if isinstance(value, str) and len(value) > _MAX_BODY_CHARS:
            return f'{value[:_MAX_BODY_CHARS]}…'
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    text = str(value)
    if len(text) > _MAX_BODY_CHARS:
        return f'{text[:_MAX_BODY_CHARS]}…'
    return text
