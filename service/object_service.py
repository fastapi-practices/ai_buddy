from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.plugin.ai_buddy.crud.crud_object import ai_buddy_object_dao
from backend.plugin.ai_buddy.crud.crud_object_audit import ai_buddy_object_audit_dao
from backend.plugin.ai_buddy.crud.crud_object_ref import ai_buddy_object_ref_dao
from backend.plugin.ai_buddy.enums import (
    AIBuddyObjectAuditAction,
    AIBuddyObjectAvailability,
    AIBuddyObjectKind,
    AIBuddyObjectLocation,
    AIBuddyObjectState,
)
from backend.plugin.ai_buddy.model.object import AIBuddyObject
from backend.plugin.ai_buddy.model.object_audit import AIBuddyObjectAudit
from backend.plugin.ai_buddy.model.object_ref import AIBuddyObjectRef
from backend.plugin.ai_buddy.schema.object import (
    AIBuddyObjectGarbageCollectParam,
    GetAIBuddyObjectEchoDetail,
    GetAIBuddyObjectGarbageCollectDetail,
)
from backend.plugin.s3.crud.crud_storage import s3_storage_dao
from backend.plugin.s3.utils.file_ops import delete_object, get_operator, remove_prefix
from backend.utils.timezone import timezone

_GC_BATCH_SIZE = 200
# 没有持有者的临时对象保留更短，其余使用 AI_BUDDY_OBJECT_GC_GRACE_HOURS
_RETENTION_HOURS = {'tool_output': 6, 'attachment': 24}


class AIBuddyObjectService:
    """AI 统一对象服务类，统一管理附件、产物、工作区文件等对象的位置、引用与回收"""

    @staticmethod
    async def get(*, db: AsyncSession, pk: int, user_id: int) -> AIBuddyObject:
        """
        获取当前用户的对象

        :param db: 数据库会话
        :param pk: 对象 ID
        :param user_id: 用户 ID
        :return:
        """
        obj = await ai_buddy_object_dao.get_owned(db, pk, user_id)
        if obj is None:
            raise errors.NotFoundError(msg='对象不存在')
        return obj

    @staticmethod
    async def get_audits(*, db: AsyncSession, pk: int, user_id: int) -> Sequence[AIBuddyObjectAudit]:
        """
        获取对象审计记录

        :param db: 数据库会话
        :param pk: 对象 ID
        :param user_id: 用户 ID
        :return:
        """
        if await ai_buddy_object_dao.get_owned(db, pk, user_id) is None:
            raise errors.NotFoundError(msg='对象不存在')
        return await ai_buddy_object_audit_dao.get_all(db, pk)

    @staticmethod
    async def record(
        *,
        db: AsyncSession,
        object_id: int,
        action: AIBuddyObjectAuditAction,
        actor_id: int | None,
        detail: dict[str, str | int | None] | None = None,
    ) -> None:
        """
        追加对象审计记录

        :param db: 数据库会话
        :param object_id: 对象 ID
        :param action: 审计动作
        :param actor_id: 操作用户 ID，系统任务为空
        :param detail: 审计详情
        :return:
        """
        await ai_buddy_object_audit_dao.create(
            db, AIBuddyObjectAudit(object_id=object_id, action=action.value, actor_id=actor_id, detail=detail)
        )

    async def register(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        kind: AIBuddyObjectKind,
        location: AIBuddyObjectLocation,
        object_key: str,
        storage_id: int | None = None,
        sha256: str | None = None,
        size: int | None = None,
        mime_type: str | None = None,
    ) -> AIBuddyObject:
        """
        登记对象，相同位置和对象键只保留一份记录

        :param db: 数据库会话
        :param user_id: 所属用户 ID
        :param kind: 对象类型
        :param location: 对象位置
        :param object_key: 对象键
        :param storage_id: 对象存储 ID，云端对象必填
        :param sha256: 内容 SHA-256 摘要
        :param size: 字节数
        :param mime_type: 媒体类型
        :return:
        """
        if location == AIBuddyObjectLocation.s3 and storage_id is None:
            raise errors.RequestError(msg='云端对象必须记录对象存储')
        obj = await ai_buddy_object_dao.get_by_key(db, location.value, storage_id, object_key)
        if obj is not None:
            if obj.user_id != user_id:
                raise errors.ForbiddenError(msg='对象不属于当前用户')
            obj.sha256 = sha256 or obj.sha256
            obj.size = size if size is not None else obj.size
            obj.mime_type = mime_type or obj.mime_type
            if obj.state == AIBuddyObjectState.deleted.value:
                # 调用方已重新写入存储内容，旧记录恢复为可引用的新对象
                obj.state = AIBuddyObjectState.active.value
                obj.ref_count = 0
                obj.tombstoned_time = None
                obj.delete_after_time = None
                obj.physically_deleted_time = None
                await self.record(db=db, object_id=obj.id, action=AIBuddyObjectAuditAction.register, actor_id=user_id)
            return obj
        obj = AIBuddyObject(
            user_id=user_id,
            kind=kind.value,
            location=location.value,
            object_key=object_key,
            storage_id=storage_id,
            sha256=sha256,
            size=size,
            mime_type=mime_type,
        )
        await ai_buddy_object_dao.create(db, obj)
        await self.record(db=db, object_id=obj.id, action=AIBuddyObjectAuditAction.register, actor_id=user_id)
        return obj

    async def register_expiring(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        kind: AIBuddyObjectKind,
        object_key: str,
        storage_id: int,
        size: int | None = None,
        sha256: str | None = None,
        mime_type: str | None = None,
    ) -> AIBuddyObject:
        """
        登记没有持有者、只按保留期到期的云端对象，重复写入会重新计算到期时间

        :param db: 数据库会话
        :param user_id: 所属用户 ID
        :param kind: 对象类型
        :param object_key: 对象键
        :param storage_id: 对象存储 ID
        :param size: 字节数
        :param sha256: 内容 SHA-256 摘要
        :param mime_type: 媒体类型
        :return:
        """
        obj = await self.register(
            db=db,
            user_id=user_id,
            kind=kind,
            location=AIBuddyObjectLocation.s3,
            object_key=object_key,
            storage_id=storage_id,
            sha256=sha256,
            size=size,
            mime_type=mime_type,
        )
        if obj.ref_count == 0 and obj.state != AIBuddyObjectState.deleted.value:
            now = timezone.now()
            obj.state = AIBuddyObjectState.tombstoned.value
            obj.tombstoned_time = now
            obj.delete_after_time = now + timedelta(hours=max(1, self._retention_hours(kind=obj.kind)))
        return obj

    async def add_reference(
        self, *, db: AsyncSession, obj: AIBuddyObject, owner_type: str, owner_id: str, actor_id: int | None
    ) -> None:
        """
        登记引用，重复登记同一引用方不会增加计数，墓碑对象会因新引用恢复

        :param db: 数据库会话
        :param obj: 对象记录
        :param owner_type: 引用方类型
        :param owner_id: 引用方 ID
        :param actor_id: 操作用户 ID
        :return:
        """
        obj = await ai_buddy_object_dao.get_for_update(db, obj.id) or obj
        if obj.state == AIBuddyObjectState.deleted.value:
            raise errors.ConflictError(msg='对象已被物理删除，无法再引用')
        if await ai_buddy_object_ref_dao.get_by_owner(db, obj.id, owner_type, owner_id) is None:
            await ai_buddy_object_ref_dao.create(
                db, AIBuddyObjectRef(object_id=obj.id, owner_type=owner_type, owner_id=owner_id)
            )
            await self.record(
                db=db,
                object_id=obj.id,
                action=AIBuddyObjectAuditAction.reference,
                actor_id=actor_id,
                detail={'owner_type': owner_type, 'owner_id': owner_id},
            )
        obj.ref_count = await ai_buddy_object_ref_dao.count(db, obj.id)
        if obj.state == AIBuddyObjectState.tombstoned.value:
            obj.state = AIBuddyObjectState.active.value
            obj.tombstoned_time = None
            obj.delete_after_time = None
            await self.record(db=db, object_id=obj.id, action=AIBuddyObjectAuditAction.revive, actor_id=actor_id)

    async def remove_reference(
        self, *, db: AsyncSession, obj: AIBuddyObject, owner_type: str, owner_id: str, actor_id: int | None
    ) -> None:
        """
        移除引用，引用归零后对象进入墓碑，宽限期结束才允许物理删除

        :param db: 数据库会话
        :param obj: 对象记录
        :param owner_type: 引用方类型
        :param owner_id: 引用方 ID
        :param actor_id: 操作用户 ID
        :return:
        """
        obj = await ai_buddy_object_dao.get_for_update(db, obj.id) or obj
        removed = await ai_buddy_object_ref_dao.delete_by_owner(db, obj.id, owner_type, owner_id)
        if removed:
            await self.record(
                db=db,
                object_id=obj.id,
                action=AIBuddyObjectAuditAction.unreference,
                actor_id=actor_id,
                detail={'owner_type': owner_type, 'owner_id': owner_id},
            )
        obj.ref_count = await ai_buddy_object_ref_dao.count(db, obj.id)
        if obj.ref_count == 0 and obj.state == AIBuddyObjectState.active.value:
            now = timezone.now()
            obj.state = AIBuddyObjectState.tombstoned.value
            obj.tombstoned_time = now
            hours = self._retention_hours(kind=obj.kind)
            obj.delete_after_time = now + timedelta(hours=max(1, hours))
            await self.record(db=db, object_id=obj.id, action=AIBuddyObjectAuditAction.tombstone, actor_id=actor_id)

    @staticmethod
    def _retention_hours(*, kind: str) -> int:
        """
        按对象类型计算墓碑保留小时数，未单独指定的类型使用默认宽限期

        :param kind: 对象类型
        :return:
        """
        return _RETENTION_HOURS.get(kind, settings.AI_BUDDY_OBJECT_GC_GRACE_HOURS)

    async def track_conversation_attachment(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        conversation_id: str,
        object_key: str,
        storage_id: int,
        size: int,
        mime_type: str | None,
    ) -> None:
        """
        登记聊天附件并让对话引用它，同一附件被多个对话引用时按对话分别计数

        :param db: 数据库会话
        :param user_id: 对话所属用户 ID
        :param conversation_id: 对话 ID
        :param object_key: 附件对象键，内容摘要即文件名
        :param storage_id: 对象存储 ID
        :param size: 字节数
        :param mime_type: 媒体类型
        :return:
        """
        stored = await self.register(
            db=db,
            user_id=user_id,
            kind=AIBuddyObjectKind.attachment,
            location=AIBuddyObjectLocation.s3,
            object_key=object_key,
            storage_id=storage_id,
            sha256=object_key.rsplit('/', 1)[-1],
            size=size,
            mime_type=mime_type,
        )
        await self.add_reference(
            db=db, obj=stored, owner_type='conversation', owner_id=conversation_id, actor_id=user_id
        )

    async def release_owner(self, *, db: AsyncSession, owner_type: str, owner_id: str, actor_id: int | None) -> int:
        """
        释放引用方持有的全部引用，无人引用的对象进入墓碑，由回收任务在宽限期后清理

        :param db: 数据库会话
        :param owner_type: 引用方类型
        :param owner_id: 引用方 ID
        :param actor_id: 操作用户 ID
        :return:
        """
        refs = await ai_buddy_object_ref_dao.get_all_by_owner(db, owner_type, owner_id)
        for ref in refs:
            obj = await ai_buddy_object_dao.select_model(db, ref.object_id)
            if obj is not None:
                await self.remove_reference(db=db, obj=obj, owner_type=owner_type, owner_id=owner_id, actor_id=actor_id)
        return len(refs)

    async def echo(self, *, db: AsyncSession, pk: int, user_id: int) -> GetAIBuddyObjectEchoDetail:
        """
        回显对象并校验云端对象是否仍可读，缺失时返回可解释状态

        :param db: 数据库会话
        :param pk: 对象 ID
        :param user_id: 用户 ID
        :return:
        """
        obj = await self.get(db=db, pk=pk, user_id=user_id)
        await self.record(db=db, object_id=obj.id, action=AIBuddyObjectAuditAction.read, actor_id=user_id)
        if obj.state == AIBuddyObjectState.deleted.value:
            availability = AIBuddyObjectAvailability.deleted
        elif obj.state == AIBuddyObjectState.tombstoned.value:
            availability = AIBuddyObjectAvailability.tombstoned
        elif obj.location != AIBuddyObjectLocation.s3.value:
            availability = AIBuddyObjectAvailability.client_side
        else:
            availability = await self._probe_s3(db=db, obj=obj)
        return GetAIBuddyObjectEchoDetail.model_validate({'object': obj, 'availability': availability})

    @staticmethod
    async def _probe_s3(*, db: AsyncSession, obj: AIBuddyObject) -> AIBuddyObjectAvailability:
        """
        探测云端对象是否可读

        :param db: 数据库会话
        :param obj: 云端对象
        :return:
        """
        storage = await s3_storage_dao.get(db, obj.storage_id) if obj.storage_id else None
        if storage is None or storage.status != StatusType.enable.value:
            return AIBuddyObjectAvailability.storage_unavailable
        try:
            await get_operator(storage).stat(obj.object_key)
        except Exception as exc:
            log.warning(f'统一对象探测失败 object_id={obj.id}: {exc!r}')
            return AIBuddyObjectAvailability.missing
        return AIBuddyObjectAvailability.available

    async def collect_garbage(
        self, *, db: AsyncSession, user_id: int | None, obj: AIBuddyObjectGarbageCollectParam
    ) -> GetAIBuddyObjectGarbageCollectDetail:
        """
        预览或物理删除宽限期已过且无引用的墓碑对象，每次删除都留下审计记录

        :param db: 数据库会话
        :param user_id: 限定的用户 ID，为空时扫描全部用户
        :param obj: 回收参数
        :return:
        """
        limit = obj.limit or _GC_BATCH_SIZE
        candidates = await ai_buddy_object_dao.get_garbage_candidates(
            db, now=timezone.now(), user_id=user_id, limit=limit
        )
        result = GetAIBuddyObjectGarbageCollectDetail(
            candidates=[item.id for item in candidates], deleted=[], failed=[]
        )
        if obj.dry_run:
            return result
        for item in candidates:
            if await ai_buddy_object_ref_dao.count(db, item.id) > 0:
                # 候选查询之后又出现了新引用，计数落后于事实，交给引用方的流程恢复
                result.candidates.remove(item.id)
                continue
            try:
                await self._delete_physically(db=db, obj=item)
            except Exception as exc:
                log.warning(f'统一对象物理删除失败 object_id={item.id}: {exc!r}')
                await self.record(
                    db=db,
                    object_id=item.id,
                    action=AIBuddyObjectAuditAction.delete_failed,
                    actor_id=user_id,
                    detail={'error': type(exc).__name__},
                )
                result.failed.append(item.id)
                continue
            item.state = AIBuddyObjectState.deleted.value
            item.physically_deleted_time = timezone.now()
            await self.record(
                db=db,
                object_id=item.id,
                action=AIBuddyObjectAuditAction.delete,
                actor_id=user_id,
                detail={'location': item.location, 'object_key': item.object_key},
            )
            result.deleted.append(item.id)
        return result

    @staticmethod
    async def _delete_physically(*, db: AsyncSession, obj: AIBuddyObject) -> None:
        """
        从存储中清除对象，以 / 结尾的对象键按目录前缀整体清除，非云端对象由所属客户端清理，服务端只记录删除结果

        :param db: 数据库会话
        :param obj: 对象记录
        :return:
        """
        if obj.location != AIBuddyObjectLocation.s3.value:
            return
        storage = await s3_storage_dao.get(db, obj.storage_id) if obj.storage_id else None
        if storage is None:
            raise errors.NotFoundError(msg='对象存储不存在')
        if obj.object_key.endswith('/'):
            await remove_prefix(storage, obj.object_key)
        else:
            await delete_object(storage, obj.object_key)


ai_buddy_object_service: AIBuddyObjectService = AIBuddyObjectService()
