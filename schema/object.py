from datetime import datetime

from pydantic import ConfigDict, Field

from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import (
    AIBuddyObjectAuditAction,
    AIBuddyObjectAvailability,
    AIBuddyObjectKind,
    AIBuddyObjectLocation,
    AIBuddyObjectState,
)


class GetAIBuddyObjectDetail(SchemaBase):
    """统一对象元数据，同时可作为删除证明"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='对象 ID')
    user_id: int = Field(description='所属用户 ID')
    kind: AIBuddyObjectKind = Field(description='对象类型')
    location: AIBuddyObjectLocation = Field(description='对象位置')
    storage_id: int | None = Field(None, description='对象存储 ID')
    object_key: str = Field(description='对象键')
    sha256: str | None = Field(None, description='内容 SHA-256 摘要')
    size: int | None = Field(None, description='字节数')
    mime_type: str | None = Field(None, description='媒体类型')
    ref_count: int = Field(description='引用计数')
    state: AIBuddyObjectState = Field(description='生命周期状态')
    tombstoned_time: datetime | None = Field(None, description='墓碑时间')
    delete_after_time: datetime | None = Field(None, description='宽限期结束时间')
    physically_deleted_time: datetime | None = Field(None, description='物理删除时间，已填写即表示对象已从存储清除')
    created_time: datetime = Field(description='创建时间')


class GetAIBuddyObjectEchoDetail(SchemaBase):
    """统一对象回显，缺失时给出可解释状态"""

    object: GetAIBuddyObjectDetail = Field(description='对象元数据')
    availability: AIBuddyObjectAvailability = Field(
        description='可用性：available 云端可读，client_side 位于客户端或沙箱需由对应端读取，其余为不可读原因'
    )


class GetAIBuddyObjectAuditDetail(SchemaBase):
    """统一对象审计记录"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='审计 ID')
    object_id: int = Field(description='对象 ID')
    action: AIBuddyObjectAuditAction = Field(description='审计动作')
    actor_id: int | None = Field(None, description='操作用户 ID，系统任务为空')
    detail: dict[str, str | int | None] | None = Field(None, description='审计详情')
    created_time: datetime = Field(description='发生时间')


class AIBuddyObjectGarbageCollectParam(SchemaBase):
    """对象回收参数"""

    dry_run: bool = Field(True, description='默认仅预览候选，设为 false 才会物理删除')
    limit: int | None = Field(None, description='本次最多处理条数，默认使用服务端批量配置')


class GetAIBuddyObjectGarbageCollectDetail(SchemaBase):
    """对象回收结果"""

    candidates: list[int] = Field(description='宽限期已过且无引用的对象 ID')
    deleted: list[int] = Field(description='已物理删除的对象 ID')
    failed: list[int] = Field(description='物理删除失败的对象 ID')
