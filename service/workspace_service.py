import hashlib
import re

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.plugin.ai_buddy.crud.crud_workspace import ai_buddy_workspace_dao
from backend.plugin.ai_buddy.crud.crud_workspace_file import ai_buddy_workspace_file_dao
from backend.plugin.ai_buddy.enums import (
    AIBuddyWorkspaceBackend,
    AIBuddyWorkspaceFileState,
)
from backend.plugin.ai_buddy.model import AIBuddyWorkspace, AIBuddyWorkspaceFile
from backend.plugin.ai_buddy.schema.workspace import (
    AIBuddyWorkspaceGarbageCollectParam,
    CreateAIBuddyWorkspaceParam,
    GetAIBuddyWorkspaceGarbageCollectDetail,
    UpdateAIBuddyWorkspaceParam,
)
from backend.plugin.ai_buddy.schema.workspace_file import (
    CreateAIBuddyWorkspaceFileParam,
    GetAIBuddyWorkspaceFileDetail,
    UpsertAIBuddyWorkspaceFileParam,
)
from backend.plugin.ai_buddy.utils.workspace import (
    normalize_workspace_object_prefix,
    normalize_workspace_path,
    validate_workspace_id,
)
from backend.plugin.s3.crud.crud_storage import s3_storage_dao
from backend.plugin.s3.utils.file_ops import delete_object, get_bytes, get_operator, put_bytes

_SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')
_MEDIA_TYPE_PATTERN = re.compile(r'^[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+$')
_OBJECT_KEY_MAX_LENGTH = 1024


class AIBuddyWorkspaceService:
    """AI 工作区服务类"""

    @staticmethod
    async def get_all(*, db: AsyncSession, user_id: int) -> Sequence[AIBuddyWorkspace]:
        """获取当前用户所有工作区"""
        return await ai_buddy_workspace_dao.get_all(db, user_id)

    @staticmethod
    async def get(*, db: AsyncSession, user_id: int, workspace_id: str, for_update: bool = False) -> AIBuddyWorkspace:
        """获取当前用户工作区"""
        normalized_workspace_id = validate_workspace_id(workspace_id.strip())
        workspace = await ai_buddy_workspace_dao.get(db, user_id, normalized_workspace_id, for_update=for_update)
        if workspace is None:
            raise errors.NotFoundError(msg='工作区不存在')
        return workspace

    @staticmethod
    async def create(*, db: AsyncSession, user_id: int, obj: CreateAIBuddyWorkspaceParam) -> AIBuddyWorkspace:
        """创建当前用户工作区"""
        workspace_id = obj.workspace_id.strip()
        name = (obj.name or workspace_id).strip()
        if not name:
            raise errors.RequestError(msg='工作区名称不能为空')
        if await ai_buddy_workspace_dao.get(db, user_id, workspace_id):
            raise errors.ConflictError(msg='工作区已存在')
        object_prefix = normalize_workspace_object_prefix(
            user_id=user_id,
            workspace_id=workspace_id,
            prefix=obj.object_prefix,
        )
        payload = obj.model_copy(update={'workspace_id': workspace_id, 'name': name, 'object_prefix': object_prefix})
        try:
            async with db.begin_nested():
                return await ai_buddy_workspace_dao.create(db, user_id, payload)
        except IntegrityError as exc:
            raise errors.ConflictError(msg='工作区已由其他请求创建，请刷新后重试') from exc

    async def get_or_create_cloud(
        self, *, db: AsyncSession, user_id: int, workspace_id: str, name: str
    ) -> AIBuddyWorkspace:
        """
        获取当前用户的云端工作区，不存在时创建

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param workspace_id: 工作区 ID
        :param name: 创建时使用的工作区名称
        :return:
        """
        workspace = await ai_buddy_workspace_dao.get(db, user_id, workspace_id)
        if workspace is None:
            try:
                workspace = await self.create(
                    db=db,
                    user_id=user_id,
                    obj=CreateAIBuddyWorkspaceParam(
                        workspace_id=workspace_id, name=name, backend=AIBuddyWorkspaceBackend.cloud
                    ),
                )
            except errors.ConflictError:
                # 并发请求已抢先创建，加锁读取已提交的记录
                workspace = await self.get(db=db, user_id=user_id, workspace_id=workspace_id, for_update=True)
        if workspace.backend != AIBuddyWorkspaceBackend.cloud:
            raise errors.RequestError(msg='工作区不是云端后端')
        return workspace

    async def update(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        workspace_id: str,
        obj: UpdateAIBuddyWorkspaceParam,
    ) -> int:
        """更新当前用户工作区"""
        workspace = await self.get(db=db, user_id=user_id, workspace_id=workspace_id, for_update=True)
        self._check_revision(expected=obj.revision, current=workspace.revision, label='工作区')
        payload = obj.model_dump(exclude_unset=True, exclude={'revision'})
        if 'name' in payload:
            payload['name'] = payload['name'].strip()
            if not payload['name']:
                raise errors.RequestError(msg='工作区名称不能为空')
        if 'object_prefix' in payload:
            payload['object_prefix'] = normalize_workspace_object_prefix(
                user_id=user_id,
                workspace_id=workspace.workspace_id,
                prefix=payload['object_prefix'],
            )
        if payload:
            updated = await ai_buddy_workspace_dao.update_if_revision(db, workspace.id, workspace.revision, payload)
            if updated == 0:
                raise errors.ConflictError(msg='工作区版本已变化，请刷新后重试')
            return updated
        return 0

    async def delete(self, *, db: AsyncSession, user_id: int, workspace_id: str) -> int:
        """删除当前用户工作区"""
        workspace = await self.get(db=db, user_id=user_id, workspace_id=workspace_id, for_update=True)
        return await ai_buddy_workspace_dao.delete(db, user_id, workspace.workspace_id)

    async def get_files(self, *, db: AsyncSession, user_id: int, workspace_id: str) -> Sequence[AIBuddyWorkspaceFile]:
        """获取当前用户工作区文件清单"""
        workspace = await self.get(db=db, user_id=user_id, workspace_id=workspace_id)
        return await ai_buddy_workspace_file_dao.get_all(db, user_id, workspace.workspace_id)

    async def upsert_file(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        workspace_id: str,
        obj: UpsertAIBuddyWorkspaceFileParam,
    ) -> GetAIBuddyWorkspaceFileDetail:
        """登记或更新当前用户工作区文件清单"""
        workspace = await self.get(db=db, user_id=user_id, workspace_id=workspace_id, for_update=True)
        existing = await ai_buddy_workspace_file_dao.get(db, user_id, workspace.workspace_id, obj.relative_path)
        object_key = self._validate_object_key(
            object_key=obj.object_key,
            object_prefix=workspace.object_prefix,
            relative_path=obj.relative_path,
        )
        if object_key is None and workspace.backend == AIBuddyWorkspaceBackend.cloud:
            object_key = f'{workspace.object_prefix}/{obj.relative_path}'
        self._validate_upload_revision(existing=existing, expected_revision=obj.revision)
        if existing is None:
            payload = obj.model_copy(update={'object_key': object_key, 'revision': 0})
            try:
                file = await ai_buddy_workspace_file_dao.create(db, user_id, workspace.workspace_id, payload)
            except IntegrityError as exc:
                raise errors.ConflictError(msg='工作区文件已由其他请求创建，请刷新后重试') from exc
            workspace.revision += 1
            return GetAIBuddyWorkspaceFileDetail.model_validate(file)
        payload = obj.model_dump(exclude_unset=True, exclude={'relative_path', 'revision'})
        if object_key is not None:
            payload['object_key'] = object_key
        payload['revision'] = existing.revision + 1
        updated = await ai_buddy_workspace_file_dao.update_if_revision(db, existing.id, existing.revision, payload)
        if updated == 0:
            raise errors.ConflictError(msg='文件版本已变化，请刷新后重试')
        for key, value in payload.items():
            setattr(existing, key, value)
        workspace.revision += 1
        return GetAIBuddyWorkspaceFileDetail.model_validate(existing)

    async def upload_bytes(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        workspace_id: str,
        relative_path: str,
        file: UploadFile,
        expected_revision: int | None = None,
        expected_size: int | None = None,
        expected_sha256: str | None = None,
    ) -> GetAIBuddyWorkspaceFileDetail:
        """上传工作区文件字节并按文件版本提交清单"""
        workspace = await self.get(db=db, user_id=user_id, workspace_id=workspace_id, for_update=True)
        if workspace.backend != AIBuddyWorkspaceBackend.cloud:
            raise errors.RequestError(msg='本地或沙箱工作区请通过对应执行端读写文件')
        normalized_path = normalize_workspace_path(relative_path)
        existing = await ai_buddy_workspace_file_dao.get(
            db,
            user_id,
            workspace.workspace_id,
            normalized_path,
        )
        self._validate_upload_revision(existing=existing, expected_revision=expected_revision)

        data, digest = await self._read_workspace_file(
            file=file,
            expected_size=expected_size,
            expected_sha256=expected_sha256,
        )
        mime_type = (file.content_type or 'application/octet-stream').split(';', 1)[0].strip()
        if _MEDIA_TYPE_PATTERN.fullmatch(mime_type) is None:
            raise errors.RequestError(msg='文件媒体类型非法')
        object_key = f'{workspace.object_prefix}/objects/{digest}/{normalized_path}'
        self._validate_object_key(
            object_key=object_key,
            object_prefix=workspace.object_prefix,
            relative_path=normalized_path,
        )
        storage = await s3_storage_dao.get_default(db)
        if storage is None:
            raise errors.RequestError(msg='未配置默认 S3 存储')
        if (
            existing is not None
            and existing.state != AIBuddyWorkspaceFileState.deleted
            and existing.size == len(data)
            and existing.sha256 == digest
            and existing.mime_type == mime_type
            and existing.storage_id == storage.id
        ):
            return GetAIBuddyWorkspaceFileDetail.model_validate(existing)

        await put_bytes(storage, object_key, data)
        if existing is None:
            payload = CreateAIBuddyWorkspaceFileParam(
                relative_path=normalized_path,
                object_key=object_key,
                storage_id=storage.id,
                size=len(data),
                sha256=digest,
                mime_type=mime_type,
                state=AIBuddyWorkspaceFileState.ready,
                revision=0,
            )
            try:
                created = await ai_buddy_workspace_file_dao.create(db, user_id, workspace.workspace_id, payload)
            except IntegrityError as exc:
                raise errors.ConflictError(msg='工作区文件已由其他请求创建，请刷新后重试') from exc
            workspace.revision += 1
            return GetAIBuddyWorkspaceFileDetail.model_validate(created)

        payload = {
            'object_key': object_key,
            'storage_id': storage.id,
            'size': len(data),
            'sha256': digest,
            'mime_type': mime_type,
            'state': AIBuddyWorkspaceFileState.ready.value,
            'revision': existing.revision + 1,
        }
        updated = await ai_buddy_workspace_file_dao.update_if_revision(db, existing.id, existing.revision, payload)
        if updated == 0:
            raise errors.ConflictError(msg='文件版本已变化，请刷新后重试')
        for key, value in payload.items():
            setattr(existing, key, value)
        workspace.revision += 1
        return GetAIBuddyWorkspaceFileDetail.model_validate(existing)

    async def delete_file(
        self, *, db: AsyncSession, user_id: int, workspace_id: str, relative_path: str, revision: int
    ) -> GetAIBuddyWorkspaceFileDetail:
        """
        按文件版本写入删除标记，旧对象等待宽限期后回收

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param workspace_id: 工作区 ID
        :param relative_path: 相对路径
        :param revision: 客户端基于的文件版本
        :return:
        """
        workspace = await self.get(db=db, user_id=user_id, workspace_id=workspace_id, for_update=True)
        path = normalize_workspace_path(relative_path)
        file = await ai_buddy_workspace_file_dao.get(db, user_id, workspace.workspace_id, path)
        if file is None:
            raise errors.NotFoundError(msg='工作区文件不存在')
        self._check_revision(expected=revision, current=file.revision, label='文件')
        if file.state == AIBuddyWorkspaceFileState.deleted:
            return GetAIBuddyWorkspaceFileDetail.model_validate(file)
        payload = {'state': AIBuddyWorkspaceFileState.deleted.value, 'revision': file.revision + 1}
        if not await ai_buddy_workspace_file_dao.update_if_revision(db, file.id, file.revision, payload):
            raise errors.ConflictError(msg='文件版本已变化，请刷新后重试')
        file.state = AIBuddyWorkspaceFileState.deleted.value
        file.revision += 1
        workspace.revision += 1
        return GetAIBuddyWorkspaceFileDetail.model_validate(file)

    async def collect_garbage(
        self, *, db: AsyncSession, user_id: int, workspace_id: str, obj: AIBuddyWorkspaceGarbageCollectParam
    ) -> GetAIBuddyWorkspaceGarbageCollectDetail:
        """
        回收默认存储内超过宽限期且不被文件清单引用的内容对象

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param workspace_id: 工作区 ID
        :param obj: 预览开关及扫描边界
        :return:
        """
        workspace = await self.get(db=db, user_id=user_id, workspace_id=workspace_id, for_update=True)
        self._check_revision(expected=obj.revision, current=workspace.revision, label='工作区')
        if workspace.backend != AIBuddyWorkspaceBackend.cloud:
            raise errors.RequestError(msg='对象回收仅适用于云端工作区')
        prefix = f'{workspace.object_prefix}/objects/'
        if obj.cursor is not None and not obj.cursor.startswith(prefix):
            raise errors.RequestError(msg='回收游标不属于当前工作区')
        storage = await s3_storage_dao.get_default(db)
        if storage is None or storage.status != StatusType.enable.value:
            raise errors.RequestError(msg='未配置可用的默认 S3 存储')
        files = await ai_buddy_workspace_file_dao.get_all(db, user_id, workspace.workspace_id)
        referenced = {
            file.object_key
            for file in files
            if file.state != AIBuddyWorkspaceFileState.deleted and file.storage_id in (None, storage.id)
        }
        cutoff = datetime.now(UTC) - timedelta(hours=max(1, settings.AI_BUDDY_WORKSPACE_GC_GRACE_HOURS))
        result = GetAIBuddyWorkspaceGarbageCollectDetail(scanned=0, candidates=[], deleted=[], failed=[])
        operator = get_operator(storage)
        entries = await operator.list(prefix, recursive=True, start_after=obj.cursor)
        last_path = None
        async for entry in entries:
            if result.scanned >= obj.limit:
                result.next_cursor = last_path
                break
            result.scanned += 1
            last_path = entry.path
            suffix = entry.path.removeprefix(prefix).split('/', 1)
            if (
                entry.path.endswith('/')
                or entry.path in referenced
                or not entry.path.startswith(prefix)
                or len(suffix) != 2
                or not _SHA256_PATTERN.fullmatch(suffix[0])
            ):
                continue
            metadata = await operator.stat(entry.path)
            if (
                metadata.last_modified is None
                or metadata.last_modified.tzinfo is None
                or metadata.last_modified.astimezone(UTC) >= cutoff
            ):
                continue
            result.candidates.append(entry.path)
            if obj.dry_run:
                continue
            try:
                await delete_object(storage, entry.path)
                result.deleted.append(entry.path)
            except Exception as exc:
                log.warning(f'工作区对象回收失败 workspace_id={workspace_id} key={entry.path}: {exc!r}')
                result.failed.append(entry.path)
        return result

    async def download_bytes(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        workspace_id: str,
        relative_path: str,
        expected_revision: int | None = None,
    ) -> tuple[bytes, GetAIBuddyWorkspaceFileDetail]:
        """下载工作区文件字节并校验清单摘要"""
        workspace = await self.get(db=db, user_id=user_id, workspace_id=workspace_id)
        if workspace.backend != AIBuddyWorkspaceBackend.cloud:
            raise errors.RequestError(msg='本地或沙箱工作区请通过对应执行端读写文件')
        normalized_path = normalize_workspace_path(relative_path)
        file = await ai_buddy_workspace_file_dao.get(db, user_id, workspace.workspace_id, normalized_path)
        if file is None or file.state == AIBuddyWorkspaceFileState.deleted or not file.object_key:
            raise errors.NotFoundError(msg='工作区文件不存在')
        if expected_revision is not None:
            self._check_revision(expected=expected_revision, current=file.revision, label='文件')
        self._validate_object_key(
            object_key=file.object_key,
            object_prefix=workspace.object_prefix,
            relative_path=normalized_path,
        )
        if file.size is None or file.sha256 is None:
            raise errors.RequestError(msg='工作区文件清单缺少完整校验信息')
        storage = (
            await s3_storage_dao.get(db, file.storage_id) if file.storage_id else await s3_storage_dao.get_default(db)
        )
        if storage is None or storage.status != StatusType.enable.value:
            raise errors.NotFoundError(msg='工作区文件存储不可用')
        try:
            data = await get_bytes(storage, file.object_key)
        except Exception as exc:
            raise errors.NotFoundError(msg='工作区文件对象不存在') from exc
        if file.size is not None and file.size != len(data):
            raise errors.RequestError(msg='工作区文件对象大小校验失败')
        if file.sha256 is not None and file.sha256 != hashlib.sha256(data).hexdigest():
            raise errors.RequestError(msg='工作区文件对象摘要校验失败')
        return data, GetAIBuddyWorkspaceFileDetail.model_validate(file)

    @staticmethod
    def _check_revision(*, expected: int | None, current: int, label: str) -> None:
        """校验客户端版本避免覆盖较新的工作区数据"""
        if expected is not None and expected != current:
            raise errors.ConflictError(msg=f'{label}版本已变化，请刷新后重试')

    @staticmethod
    def _validate_object_key(*, object_key: str | None, object_prefix: str, relative_path: str) -> str | None:
        """校验文件对象键归属于工作区前缀"""
        if object_key is None:
            return None
        if len(object_key) > _OBJECT_KEY_MAX_LENGTH:
            raise errors.RequestError(msg='文件对象键过长')
        logical_key = f'{object_prefix}/{relative_path}'
        content_prefix = f'{object_prefix}/objects/'
        content_key = object_key.removeprefix(content_prefix)
        content_parts = content_key.split('/', 1)
        is_content_key = (
            object_key.startswith(content_prefix)
            and len(content_parts) == 2
            and _SHA256_PATTERN.fullmatch(content_parts[0]) is not None
            and content_parts[1] == relative_path
        )
        if object_key != logical_key and not is_content_key:
            raise errors.RequestError(msg='文件对象键不属于当前工作区')
        return object_key

    def _validate_upload_revision(
        self, *, existing: AIBuddyWorkspaceFile | None, expected_revision: int | None
    ) -> None:
        """校验工作区文件上传的 CAS 版本"""
        if existing is None:
            if expected_revision not in (None, 0):
                raise errors.ConflictError(msg='新工作区文件版本必须为 0')
            return
        if expected_revision is None:
            raise errors.ConflictError(msg='更新工作区文件必须提供文件版本')
        self._check_revision(expected=expected_revision, current=existing.revision, label='文件')

    @staticmethod
    async def _read_workspace_file(
        *, file: UploadFile, expected_size: int | None, expected_sha256: str | None
    ) -> tuple[bytes, str]:
        """读取工作区文件并校验客户端摘要"""
        data = await file.read(settings.S3_UPLOAD_SIZE_MAX + 1)
        if len(data) > settings.S3_UPLOAD_SIZE_MAX:
            raise errors.RequestError(msg='工作区文件超过大小限制')
        if expected_size is not None and expected_size != len(data):
            raise errors.RequestError(msg='文件大小校验失败')
        digest = hashlib.sha256(data).hexdigest()
        if expected_sha256 is not None and (
            not _SHA256_PATTERN.fullmatch(expected_sha256) or expected_sha256 != digest
        ):
            raise errors.RequestError(msg='文件 SHA-256 校验失败')
        return data, digest


ai_buddy_workspace_service: AIBuddyWorkspaceService = AIBuddyWorkspaceService()
