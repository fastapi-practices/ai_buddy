from datetime import datetime

from pydantic import ConfigDict, Field, field_validator

from backend.common.exception import errors
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyWorkspaceFileState
from backend.plugin.ai_buddy.utils.workspace import normalize_workspace_path


def _relative_path(value: str) -> str:
    """
    校验工作区文件相对路径

    :param value: 待校验的相对路径
    :return:
    """
    try:
        return normalize_workspace_path(value)
    except errors.RequestError as exc:
        raise ValueError(exc.msg) from exc


def _object_key(value: str | None) -> str | None:
    """
    校验工作区对象键

    :param value: 待校验的对象键
    :return:
    """
    if value is None:
        return None
    normalized = value.strip().strip('/')
    parts = normalized.split('/')
    if not normalized or any(not part or part in {'.', '..'} for part in parts):
        raise ValueError('对象键非法')
    if any(char in normalized for char in ('\\', '\0', '\n', '\r')) or any(ord(char) < 32 for char in normalized):
        raise ValueError('对象键非法')
    return normalized


class AIBuddyWorkspaceFileSchemaBase(SchemaBase):
    """AI 工作区文件清单基础模型"""

    relative_path: str = Field(min_length=1, max_length=2048, description='工作区相对路径')
    object_key: str | None = Field(None, max_length=1024, description='对象键')
    size: int | None = Field(None, ge=0, description='文件字节数')
    sha256: str | None = Field(None, pattern=r'^[0-9a-f]{64}$', description='文件 SHA-256 摘要')
    mime_type: str | None = Field(None, max_length=128, description='媒体类型')
    state: AIBuddyWorkspaceFileState = Field(default=AIBuddyWorkspaceFileState.ready, description='文件状态')
    revision: int = Field(default=0, ge=0, description='文件版本')

    _validate_relative_path = field_validator('relative_path')(_relative_path)
    _validate_object_key = field_validator('object_key')(_object_key)


class AIBuddyWorkspaceFileUploadQueryParam(SchemaBase):
    """AI 工作区文件上传查询参数"""

    relative_path: str = Field(min_length=1, max_length=2048, description='工作区相对路径')
    revision: int | None = Field(None, ge=0, description='客户端基于的文件版本')
    size: int | None = Field(None, ge=0, description='客户端声明的文件字节数')
    sha256: str | None = Field(
        None,
        min_length=64,
        max_length=64,
        pattern=r'^[0-9a-f]{64}$',
        description='客户端声明的 SHA-256 摘要',
    )


class AIBuddyWorkspaceFileDownloadQueryParam(SchemaBase):
    """AI 工作区文件下载查询参数"""

    relative_path: str = Field(min_length=1, max_length=2048, description='工作区相对路径')
    revision: int | None = Field(None, ge=0, description='期望的文件版本')


class AIBuddyWorkspaceFileDeleteQueryParam(SchemaBase):
    """AI 工作区文件删除查询参数"""

    relative_path: str = Field(min_length=1, max_length=2048, description='工作区相对路径')
    revision: int = Field(ge=0, description='客户端基于的文件版本')


class CreateAIBuddyWorkspaceFileParam(AIBuddyWorkspaceFileSchemaBase):
    """服务端创建 AI 工作区文件清单参数"""

    storage_id: int | None = Field(None, ge=1, description='对象存储 ID')


class UpsertAIBuddyWorkspaceFileParam(AIBuddyWorkspaceFileSchemaBase):
    """登记或更新 AI 工作区文件清单参数"""


class GetAIBuddyWorkspaceFileDetail(AIBuddyWorkspaceFileSchemaBase):
    """AI 工作区文件清单详情"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='文件清单记录 ID')
    user_id: int = Field(description='用户 ID')
    workspace_id: str = Field(description='工作区 ID')
    storage_id: int | None = Field(None, ge=1, description='对象存储 ID')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')
