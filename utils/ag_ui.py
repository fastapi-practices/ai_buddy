from typing import Any

from ag_ui.core import BaseEvent, Event
from ag_ui.encoder import EventEncoder
from pydantic import TypeAdapter

_EVENT_ADAPTER = TypeAdapter(Event)
_EVENT_ENCODER = EventEncoder()


def encode_ag_ui_event(event: BaseEvent | dict[str, Any]) -> str:
    """
    通过官方模型校验并编码所有对话入口的 AG-UI 事件

    :param event: 原生事件或事件字典
    :return:
    """
    payload = event.model_dump(mode='json', by_alias=True) if isinstance(event, BaseEvent) else event
    return _EVENT_ENCODER.encode(_EVENT_ADAPTER.validate_python(payload))
