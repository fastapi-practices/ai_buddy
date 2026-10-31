from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field, field_validator

from backend.common.exception import errors
from backend.common.schema import SchemaBase
from backend.plugin.ai_buddy.enums import AIBuddyArtifactKind, AIBuddyArtifactState, AIBuddyArtifactStorageBackend
from backend.plugin.ai_buddy.utils.workspace import normalize_workspace_path, validate_workspace_id


class AIBuddyArtifactQueryParam(SchemaBase):
    """AI 产物查询参数"""

    kind: AIBuddyArtifactKind | None = Field(
        None,
        description=(
            '产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他；不传则查询全部类型'
        ),
    )


def _validate_relative_path(value: str | None) -> str | None:
    """
    校验工作区引用使用安全的 POSIX 相对路径

    :param value: 工作区相对路径
    :return:
    """
    if value is None:
        return None
    try:
        return normalize_workspace_path(value)
    except errors.RequestError as exc:
        raise ValueError(exc.msg) from exc


def _validate_workspace_id(value: str | None) -> str | None:
    """
    校验工作区标识

    :param value: 工作区标识
    :return:
    """
    if value is None:
        return None
    try:
        return validate_workspace_id(value)
    except errors.RequestError as exc:
        raise ValueError(exc.msg) from exc


class AIBuddyArtifactSchemaBase(SchemaBase):
    """AI 产物基础模型"""

    title: str = Field(description='产物标题')
    kind: AIBuddyArtifactKind = Field(
        description='产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他'
    )
    content: str = Field(description='产物内容')


class CreateAIBuddyArtifactParam(AIBuddyArtifactSchemaBase):
    """创建 AI 产物参数"""

    storage_backend: Literal[AIBuddyArtifactStorageBackend.s3] = Field(
        AIBuddyArtifactStorageBackend.s3, description='文本产物存储后端'
    )
    workspace_id: str | None = Field(None, description='工作区 ID')
    relative_path: str | None = Field(None, description='工作区相对路径')
    mime_type: str | None = Field(None, description='媒体类型')
    size: int | None = Field(None, description='文件字节数')
    sha256: str | None = Field(None, pattern=r'^[0-9a-f]{64}$', description='文件 SHA-256 摘要')
    state: AIBuddyArtifactState = Field(AIBuddyArtifactState.ready, description='产物状态')

    _validate_relative_path = field_validator('relative_path')(_validate_relative_path)
    _validate_workspace_id = field_validator('workspace_id')(_validate_workspace_id)


class RegisterAIBuddyArtifactParam(SchemaBase):
    """注册工作区产物引用参数"""

    title: str = Field(description='产物标题')
    kind: AIBuddyArtifactKind = Field(
        description='产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他'
    )
    storage_backend: AIBuddyArtifactStorageBackend = Field(description='存储后端')
    workspace_id: str | None = Field(None, description='工作区 ID')
    relative_path: str = Field(description='工作区相对路径')
    mime_type: str | None = Field(None, description='媒体类型')
    size: int | None = Field(None, description='文件字节数')
    sha256: str | None = Field(None, pattern=r'^[0-9a-f]{64}$', description='文件 SHA-256 摘要')
    state: AIBuddyArtifactState = Field(AIBuddyArtifactState.ready, description='产物状态')

    _validate_relative_path = field_validator('relative_path')(_validate_relative_path)
    _validate_workspace_id = field_validator('workspace_id')(_validate_workspace_id)


class UpdateAIBuddyArtifactParam(SchemaBase):
    """更新 AI 产物参数"""

    title: str | None = Field(None, description='产物标题')
    kind: AIBuddyArtifactKind | None = Field(
        None, description='产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他'
    )
    content: str | None = Field(None, description='产物内容')
    object_key: str | None = Field(None, description='对象键')
    storage_backend: AIBuddyArtifactStorageBackend | None = Field(None, description='存储后端')
    workspace_id: str | None = Field(None, description='工作区 ID')
    relative_path: str | None = Field(None, description='工作区相对路径')
    mime_type: str | None = Field(None, description='媒体类型')
    size: int | None = Field(None, description='文件字节数')
    sha256: str | None = Field(None, pattern=r'^[0-9a-f]{64}$', description='文件 SHA-256 摘要')
    state: AIBuddyArtifactState | None = Field(None, description='产物状态')

    _validate_relative_path = field_validator('relative_path')(_validate_relative_path)
    _validate_workspace_id = field_validator('workspace_id')(_validate_workspace_id)


class GetAIBuddyArtifactListDetail(SchemaBase):
    """AI 产物列表元数据"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description='产物 ID')
    user_id: int = Field(description='用户 ID')
    title: str = Field(description='产物标题')
    kind: AIBuddyArtifactKind = Field(
        description='产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他'
    )
    object_key: str | None = Field(None, description='对象键')
    storage_id: int | None = Field(None, description='对象存储 ID')
    storage_backend: AIBuddyArtifactStorageBackend = Field(description='存储后端')
    workspace_id: str | None = Field(None, description='工作区 ID')
    relative_path: str | None = Field(None, description='工作区相对路径')
    mime_type: str | None = Field(None, description='媒体类型')
    size: int | None = Field(None, description='文件字节数')
    sha256: str | None = Field(None, description='文件 SHA-256 摘要')
    state: AIBuddyArtifactState = Field(AIBuddyArtifactState.ready, description='产物状态')
    created_time: datetime = Field(description='创建时间')
    updated_time: datetime | None = Field(None, description='更新时间')


class GetAIBuddyArtifactDetail(GetAIBuddyArtifactListDetail):
    """AI 产物详情"""

    content: str = Field(description='产物内容')
