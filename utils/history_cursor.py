import base64
import json

from backend.common.exception import errors
from backend.plugin.ai_buddy.model.message import AIBuddyMessage


def encode_history_cursor(*, row: AIBuddyMessage) -> str:
    """
    复合顺序游标不依赖连续主键

    :param row: 消息记录
    :return:
    """
    return base64.urlsafe_b64encode(json.dumps([row.message_index, row.id]).encode()).decode().rstrip('=')


def decode_history_cursor(*, cursor: str | None) -> tuple[int, int] | None:
    """
    验证不透明历史游标

    :param cursor: 分页游标
    :return:
    """
    if cursor is None:
        return None
    try:
        if len(cursor) > 128:
            raise ValueError
        value = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError
        if any(type(item) is not int or item < 0 for item in value) or value[1] == 0:
            raise ValueError
        return value[0], value[1]
    except (ValueError, TypeError, UnicodeError) as exc:
        raise errors.RequestError(msg='历史消息游标无效') from exc
