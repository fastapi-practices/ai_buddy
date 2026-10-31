from datetime import datetime

from pydantic import ConfigDict, Field, field_validator

from backend.common.exception import errors
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import (
    AIBuddyWorkspaceBackend,
    AIBuddyWorkspaceState,
)
from backend.plugin.ai_buddy.utils.workspace import validate_workspace_id


def _workspace_id(value: str) -> str:
    """
    校验工作区标识

    :param value: 待校验的工作区 ID
    :return:
    """
    try:
        return validate_workspace_id(value.strip())
    except errors.RequestError as exc:
        raise ValueError(exc.msg) from exc


class AIBuddyWorkspaceSchemaBase(SchemaBase):
    """AI 工作区基础模型"""

    workspace_id: str = Field(description='工作区 ID')
    name: str | None = Field(None, description='工作区名称')
    backend: AIBuddyWorkspaceBackend = Field(description='工作区后端')
    object_prefix: str | None = Field(None, description='对象前缀')
    revision: int = Field(default=0, description='工作区版本')
    state: AIBuddyWorkspaceState = Field(default=AIBuddyWorkspaceState.ready, description='工作区状态')

    _validate_workspace_id = field_validator('workspace_id')(_workspace_id)


class CreateAIBuddyWorkspaceParam(AIBuddyWorkspaceSchemaBase):
    """创建 AI 工作区参数"""


class UpdateAIBuddyWorkspaceParam(SchemaBase):
    """更新 AI 工作区参数"""

    name: str | None = Field(None, description='工作区名称')
    backend: AIBuddyWorkspaceBackend | None = Field(None, description='工作区后端')
    object_prefix: str | None = Field(None, description='对象前缀')
    revision: int | None = Field(None, description='客户端基于的工作区版本')
    state: AIBuddyWorkspaceState | None = Field(None, description='工作区状态')


class GetAIBuddyWorkspaceDetail(AIBuddyWorkspaceSchemaBase):
    """AI 工作区详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='工作区记录 ID')
    user_id: int = Field(description='用户 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class AIBuddyWorkspaceGarbageCollectParam(SchemaBase):
    """回收工作区未引用的旧对象"""

    dry_run: bool = Field(True, description='默认仅预览，不删除对象')
    revision: int = Field(description='客户端基于的工作区版本')
    limit: int = Field(100, description='单次扫描对象数上限')
    cursor: str | None = Field(None, description='上次扫描返回的游标')


class GetAIBuddyWorkspaceGarbageCollectDetail(SchemaBase):
    """对象回收执行结果"""

    scanned: int = Field(description='扫描对象数')
    candidates: list[str] = Field(description='符合回收条件的对象键')
    deleted: list[str] = Field(description='已删除的对象键')
    failed: list[str] = Field(description='删除失败的对象键，可重试')
    next_cursor: str | None = Field(None, description='继续扫描的游标')
