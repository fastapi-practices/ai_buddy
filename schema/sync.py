from datetime import datetime
from typing import Literal

from pydantic import Field

from backend.common.schema import SchemaBase


class AIBuddySyncQueryParam(SchemaBase):
    """增量同步查询参数"""

    cursor: str | None = Field(None, pattern=r'^\d+\.[01]\.\d+$', description='上一次响应返回的同步游标，首次同步不传')
    limit: int = Field(100, description='本次最多返回的变更条数')


class GetAIBuddySyncChangeDetail(SchemaBase):
    """单条同步变更"""

    entity: Literal['conversation', 'message'] = Field(description='变更实体')
    row_id: int = Field(description='实体行 ID')
    conversation_id: str = Field(description='所属对话 ID')
    change: Literal['upsert', 'delete'] = Field(description='变更类型，delete 为删除墓碑')
    change_time: datetime = Field(description='变更发生时间')
    message_index: int | None = Field(None, description='会话内统一顺序号，仅消息有值')
    role: str | None = Field(None, description='消息角色，仅消息有值')
    status: str | None = Field(None, description='消息状态，仅消息有值')
    client_message_id: str | None = Field(None, description='客户端消息 ID，仅用户消息可能有值')
    title: str | None = Field(None, description='对话标题，仅对话有值')
    revision: int | None = Field(None, description='对话修订号，仅对话有值')
    source: str | None = Field(None, description='会话事实源，仅对话有值')


class GetAIBuddySyncDetail(SchemaBase):
    """增量同步结果"""

    changes: list[GetAIBuddySyncChangeDetail] = Field(
        description='按变更时间升序排列的变更，客户端应按实体行 ID 幂等合并'
    )
    next_cursor: str = Field(description='下次同步使用的游标，已追平时会回退约 2 秒以覆盖同秒写入')
    has_more: bool = Field(description='是否还有更多变更，为 true 时应立刻用 next_cursor 继续拉取')
