import hashlib
import mimetypes
import re

from collections.abc import Sequence
from io import BytesIO
from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from backend.common.exception import errors
from backend.common.pagination import cursor_paging_data
from backend.plugin.ai_buddy.crud.crud_artifact import ai_buddy_artifact_dao
from backend.plugin.ai_buddy.crud.crud_workspace_file import ai_buddy_workspace_file_dao
from backend.plugin.ai_buddy.enums import (
    AIBuddyArtifactKind,
    AIBuddyArtifactState,
    AIBuddyArtifactStorageBackend,
    AIBuddyObjectKind,
    AIBuddyObjectLocation,
    AIBuddyWorkspaceBackend,
    AIBuddyWorkspaceFileState,
)
from backend.plugin.ai_buddy.model import AIBuddyArtifact
from backend.plugin.ai_buddy.schema.artifact import (
    CreateAIBuddyArtifactParam,
    RegisterAIBuddyArtifactParam,
    UpdateAIBuddyArtifactParam,
)
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service
from backend.plugin.ai_buddy.service.workspace_service import ai_buddy_workspace_service
from backend.plugin.ai_buddy.utils.object_key import build_object_key
from backend.plugin.ai_buddy.utils.workspace import validate_workspace_id
from backend.plugin.s3.utils.text_store import read_text, require_storage, write_text

_DELIVERY_WORKSPACE_ID = 'sandbox-outbound'
_DELIVERY_WORKSPACE_NAME = '沙箱交付文件'
_FILENAME_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\]')
_FILENAME_MAX_LENGTH = 120
_MEDIA_KINDS = frozenset({'image', 'video', 'audio', 'text'})


class AIBuddyArtifactService:
    """AI 产物服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyArtifact]:
        """
        获取当前用户所有产物

        :param db: 数据库会话
        :param user_id: 用户 ID
        :return:
        """
        artifacts = await ai_buddy_artifact_dao.get_all(db, user_id)
        for artifact in artifacts:
            artifact.content = (
                await read_text(db=db, key=artifact.object_key, storage_id=artifact.storage_id)
                if artifact.object_key and not artifact.relative_path
                else ''
            )
        return artifacts

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int) -> AIBuddyArtifact:
        """
        获取产物详情

        :param db: 数据库会话
        :param pk: 产物 ID
        :param user_id: 用户 ID
        :return:
        """
        artifact = await ai_buddy_artifact_dao.get(db, pk)
        if artifact is None or artifact.user_id != user_id:
            raise errors.NotFoundError(msg='产物不存在')
        artifact.content = (
            await read_text(db=db, key=artifact.object_key, storage_id=artifact.storage_id)
            if artifact.object_key and not artifact.relative_path
            else ''
        )
        return artifact

    @staticmethod
    async def get_list(*, db: AsyncSession, user_id: int, kind: AIBuddyArtifactKind | None = None) -> dict[str, Any]:
        """
        按类型游标查询当前用户的产物元数据

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param kind: 产物类型，空则查询所有类型
        :return:
        """
        artifact_select = await ai_buddy_artifact_dao.get_select(user_id, kind)
        return await cursor_paging_data(db, artifact_select)

    async def download(self, *, db: AsyncSession, pk: int, user_id: int) -> tuple[bytes, str, str]:
        """
        下载产物并校验工作区文件与登记内容一致

        :param db: 数据库会话
        :param pk: 产物 ID
        :param user_id: 用户 ID
        :return:
        """
        artifact = await self.get(db=db, pk=pk, user_id=user_id)
        if artifact.state not in (AIBuddyArtifactState.ready, AIBuddyArtifactState.archived):
            raise errors.RequestError(msg='产物尚未就绪或已删除')
        if artifact.storage_backend in (AIBuddyArtifactStorageBackend.local, AIBuddyArtifactStorageBackend.sandbox):
            raise errors.RequestError(msg='请在产物所属的本机或沙箱工作区中打开文件')
        if artifact.storage_backend != AIBuddyArtifactStorageBackend.s3:
            raise errors.RequestError(msg='产物存储后端无效')
        if artifact.relative_path:
            if not artifact.workspace_id or artifact.size is None or not artifact.sha256:
                raise errors.RequestError(msg='文件产物缺少校验信息，请重新登记')
            data, manifest = await ai_buddy_workspace_service.download_bytes(
                db=db,
                user_id=user_id,
                workspace_id=artifact.workspace_id,
                relative_path=artifact.relative_path,
            )
            if manifest.sha256 != artifact.sha256 or manifest.size != artifact.size:
                raise errors.ConflictError(msg='工作区文件已变更，请重新登记产物后下载')
            return data, artifact.relative_path.rsplit('/', 1)[-1], 'application/octet-stream'
        if not artifact.object_key:
            raise errors.NotFoundError(msg='产物文件不存在')
        return artifact.content.encode(), f'artifact-{artifact.id}.md', 'text/markdown'

    async def create(self, *, db: AsyncSession, user_id: int, obj: CreateAIBuddyArtifactParam) -> AIBuddyArtifact:
        """
        创建产物

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param obj: 创建产物参数
        :return:
        """
        title = obj.title.strip()
        content = obj.content.strip()
        if not title:
            raise errors.RequestError(msg='产物标题不能为空')
        if not content:
            raise errors.RequestError(msg='产物内容不能为空')
        if obj.workspace_id is not None or obj.relative_path is not None:
            raise errors.RequestError(msg='文件产物请使用工作区产物登记')

        storage = await require_storage(db=db)

        artifact = await ai_buddy_artifact_dao.create(
            db,
            user_id,
            obj.model_copy(update={'title': title, 'storage_backend': AIBuddyArtifactStorageBackend.s3}),
            storage_id=storage.id,
        )
        object_key = build_object_key(user_id=user_id, kind='artifacts', pk=artifact.id)
        await write_text(db=db, key=object_key, content=content, storage_id=storage.id)
        await ai_buddy_artifact_dao.update(db, artifact.id, {'object_key': object_key})
        artifact.object_key = object_key
        artifact.content = content
        await self._track_object(
            db=db,
            user_id=user_id,
            artifact_id=artifact.id,
            object_key=object_key,
            storage_id=storage.id,
            state=AIBuddyArtifactState.ready,
            content=content,
        )
        return artifact

    @staticmethod
    async def register_reference(
        *, db: AsyncSession, user_id: int, obj: RegisterAIBuddyArtifactParam
    ) -> AIBuddyArtifact:
        """
        注册工作区产物引用

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param obj: 工作区产物引用参数
        :return:
        """
        title = obj.title.strip()
        if not title:
            raise errors.RequestError(msg='产物标题不能为空')
        workspace = None
        if obj.workspace_id is not None:
            workspace = await ai_buddy_workspace_service.get(db=db, user_id=user_id, workspace_id=obj.workspace_id)
            expected_backend = (
                AIBuddyWorkspaceBackend.cloud
                if obj.storage_backend == AIBuddyArtifactStorageBackend.s3
                else obj.storage_backend
            )
            if workspace.backend != expected_backend:
                raise errors.RequestError(msg='产物存储位置与工作区不一致')
        metadata: dict[str, str | int | None] = {}
        storage_id = None
        if obj.storage_backend == AIBuddyArtifactStorageBackend.s3:
            if workspace is None:
                raise errors.RequestError(msg='云端文件产物必须绑定工作区')
            file = await ai_buddy_workspace_file_dao.get(db, user_id, workspace.workspace_id, obj.relative_path)
            if (
                file is None
                or file.state != AIBuddyWorkspaceFileState.ready
                or not file.object_key
                or file.size is None
                or not file.sha256
            ):
                raise errors.RequestError(msg='请先上传工作区文件，再登记产物')
            if (obj.size is not None and obj.size != file.size) or (obj.sha256 and obj.sha256 != file.sha256):
                raise errors.ConflictError(msg='工作区文件已变更，请刷新后重新登记')
            metadata = {'mime_type': file.mime_type, 'size': file.size, 'sha256': file.sha256}
            storage_id = file.storage_id
        artifact = await ai_buddy_artifact_dao.create(
            db,
            user_id,
            obj.model_copy(update={'title': title, **metadata}),
            storage_id=storage_id,
        )
        artifact.content = ''
        return artifact

    async def deliver_file(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        conversation_id: str,
        filename: str,
        data: bytes,
        title: str | None,
        kind: AIBuddyArtifactKind | None,
    ) -> AIBuddyArtifact:
        """
        把服务端沙箱产出的文件字节存入云端交付工作区，并登记为文件产物

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 来源对话 ID
        :param filename: 文件名
        :param data: 文件字节
        :param title: 产物标题，为空使用文件名
        :param kind: 产物类型，为空按媒体类型推断
        :return:
        """
        name = _FILENAME_UNSAFE.sub('_', filename).strip()[:_FILENAME_MAX_LENGTH]
        if name in {'', '.', '..'}:
            raise errors.RequestError(msg='文件名无效')
        digest = hashlib.sha256(data).hexdigest()
        mime_type = mimetypes.guess_type(name)[0] or 'application/octet-stream'
        major_type = mime_type.split('/', 1)[0]
        if kind is None:
            kind = AIBuddyArtifactKind(major_type) if major_type in _MEDIA_KINDS else AIBuddyArtifactKind.other
        # 路径带内容摘要，同一路径始终对应同一内容，历史消息引用的产物不会被后续交付覆盖
        relative_path = f'{validate_workspace_id(conversation_id)}/{digest[:16]}/{name}'

        workspace = await ai_buddy_workspace_service.get_or_create_cloud(
            db=db, user_id=user_id, workspace_id=_DELIVERY_WORKSPACE_ID, name=_DELIVERY_WORKSPACE_NAME
        )
        existing = await ai_buddy_workspace_file_dao.get(db, user_id, workspace.workspace_id, relative_path)
        file = await ai_buddy_workspace_service.upload_bytes(
            db=db,
            user_id=user_id,
            workspace_id=workspace.workspace_id,
            relative_path=relative_path,
            file=UploadFile(BytesIO(data), size=len(data), filename=name, headers=Headers({'content-type': mime_type})),
            expected_revision=None if existing is None else existing.revision,
        )

        return await self.register_reference(
            db=db,
            user_id=user_id,
            obj=RegisterAIBuddyArtifactParam(
                title=(title or '').strip()[:256] or name,
                kind=kind,
                storage_backend=AIBuddyArtifactStorageBackend.s3,
                workspace_id=workspace.workspace_id,
                relative_path=relative_path,
                mime_type=file.mime_type,
                size=file.size,
                sha256=file.sha256,
            ),
        )

    async def update(self, *, db: AsyncSession, pk: int, user_id: int, obj: UpdateAIBuddyArtifactParam) -> int:
        """
        更新产物

        :param db: 数据库会话
        :param pk: 产物 ID
        :param user_id: 用户 ID
        :param obj: 更新产物参数
        :return:
        """
        artifact = await self.get(db=db, pk=pk, user_id=user_id)
        title = obj.title.strip() if obj.title is not None else None
        content = obj.content.strip() if obj.content is not None else None
        for label, value in (('标题', title), ('内容', content)):
            if value is not None and not value:
                raise errors.RequestError(msg=f'产物{label}不能为空')
        if any(
            getattr(obj, field) is not None and getattr(obj, field) != getattr(artifact, field)
            for field in ('storage_backend', 'workspace_id', 'relative_path')
        ):
            raise errors.RequestError(msg='产物存储位置不能修改，请重新登记产物')
        if artifact.relative_path and (
            content is not None
            or any(
                getattr(obj, field) is not None and getattr(obj, field) != getattr(artifact, field)
                for field in ('mime_type', 'size', 'sha256')
            )
        ):
            raise errors.RequestError(msg='文件产物请通过工作区更新后重新登记')
        payload: dict[str, str | int | None] = {'object_key': artifact.object_key}
        if content is not None:
            object_key = artifact.object_key or build_object_key(user_id=user_id, kind='artifacts', pk=pk)
            storage = await require_storage(db=db, storage_id=artifact.storage_id)
            await write_text(db=db, key=object_key, content=content, storage_id=storage.id)
            payload.update({'object_key': object_key, 'storage_id': storage.id})
        if title is not None:
            payload['title'] = title
        if obj.kind is not None:
            payload['kind'] = obj.kind
        for field in ('storage_backend', 'workspace_id', 'relative_path', 'mime_type', 'size', 'sha256', 'state'):
            value = getattr(obj, field)
            if value is not None:
                payload[field] = value
        await self._track_object(
            db=db,
            user_id=user_id,
            artifact_id=pk,
            object_key=payload['object_key'],
            storage_id=payload.get('storage_id', artifact.storage_id),
            state=obj.state or artifact.state,
            content=content,
        )
        return await ai_buddy_artifact_dao.update(db, pk, payload)

    @staticmethod
    async def _track_object(
        *,
        db: AsyncSession,
        user_id: int,
        artifact_id: int,
        object_key: str | None,
        storage_id: int | None,
        state: AIBuddyArtifactState | str,
        content: str | None,
    ) -> None:
        """
        同步产物与统一对象的引用，已删除的产物释放引用，历史产物会在更新时补登记

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param artifact_id: 产物 ID
        :param object_key: 正文对象键
        :param storage_id: 对象存储 ID
        :param state: 产物状态
        :param content: 本次写入的正文，未写入时为空
        :return:
        """
        if not object_key or storage_id is None:
            return
        stored = await ai_buddy_object_service.register(
            db=db,
            user_id=user_id,
            kind=AIBuddyObjectKind.artifact,
            location=AIBuddyObjectLocation.s3,
            object_key=object_key,
            storage_id=storage_id,
            size=len(content.encode()) if content is not None else None,
            mime_type='text/markdown',
        )
        if state == AIBuddyArtifactState.deleted:
            await ai_buddy_object_service.remove_reference(
                db=db, obj=stored, owner_type='artifact', owner_id=str(artifact_id), actor_id=user_id
            )
        else:
            await ai_buddy_object_service.add_reference(
                db=db, obj=stored, owner_type='artifact', owner_id=str(artifact_id), actor_id=user_id
            )


ai_buddy_artifact_service: AIBuddyArtifactService = AIBuddyArtifactService()
