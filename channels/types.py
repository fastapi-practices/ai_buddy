from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """归一后的通道入站消息"""

    external_id: str
    text: str
    raw: dict[str, Any]
    session_id: str | None = None
