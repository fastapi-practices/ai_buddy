import hashlib

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.enums import AIBuddyConversationSource, AIBuddyObjectKind
from backend.plugin.ai_buddy.model.object import AIBuddyObject
from backend.plugin.ai_buddy.schema.attachment import GetAIBuddyAttachmentDetail
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service
from backend.plugin.ai_buddy.utils.remote_download import download_public_file, match_content_type
from backend.plugin.s3.utils.text_store import require_storage, write_bytes

_ALLOWED_TYPES = (
    'image/',
    'audio/',
    'video/',
    'text/',
    'application/pdf',
    'application/json',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.',
)


class AIBuddyAttachmentService:
    """AI 附件服务类，上传和远程下载先进入暂存区，被对话引用后才成为正式附件"""

    async def stage_upload(self, *, db: AsyncSession, user_id: int, file: UploadFile) -> GetAIBuddyAttachmentDetail:
        """
        暂存上传的附件

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param file: 上传文件
        :return:
        """
        limit = settings.AI_BUDDY_ATTACHMENT_MAX_BYTES
        data = await file.read(limit + 1)
        return await self._stage(
            db=db,
            user_id=user_id,
            data=data,
            content_type=(file.content_type or '').split(';', 1)[0].strip().lower(),
            filename=file.filename or 'upload',
        )

    async def stage_from_url(self, *, db: AsyncSession, user_id: int, url: str) -> GetAIBuddyAttachmentDetail:
        """
        从公网地址下载并暂存附件，下载受内网拦截、重定向次数、大小与类型限制

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param url: 远程文件地址
        :return:
        """
        remote = await download_public_file(
            url=url,
            max_bytes=settings.AI_BUDDY_ATTACHMENT_MAX_BYTES,
            allowed_types=_ALLOWED_TYPES,
        )
        return await self._stage(
            db=db, user_id=user_id, data=remote.data, content_type=remote.content_type, filename=remote.filename
        )

    @staticmethod
    async def promote(*, db: AsyncSession, user_id: int, pk: int, conversation_id: str) -> AIBuddyObject:
        """
        提升暂存附件，让对话引用它后不再按暂存期到期

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param pk: 暂存对象 ID
        :param conversation_id: 引用该附件的对话 ID
        :return:
        """
        obj = await ai_buddy_object_service.get(db=db, pk=pk, user_id=user_id)
        if obj.kind != AIBuddyObjectKind.attachment.value:
            raise errors.RequestError(msg='只能提升附件对象')
        conversation = await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=conversation_id, user_id=user_id
        )
        if conversation.source == AIBuddyConversationSource.local:
            raise errors.RequestError(msg='以本机为准的对话不允许引用云端附件')
        await ai_buddy_object_service.add_reference(
            db=db, obj=obj, owner_type='conversation', owner_id=conversation_id, actor_id=user_id
        )
        return obj

    @staticmethod
    async def _stage(
        *, db: AsyncSession, user_id: int, data: bytes, content_type: str, filename: str
    ) -> GetAIBuddyAttachmentDetail:
        """
        校验并写入暂存附件，内容摘要作为对象键，相同内容只保存一份

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param data: 附件内容
        :param content_type: 媒体类型
        :param filename: 文件名
        :return:
        """
        if not data:
            raise errors.RequestError(msg='附件不能为空')
        if len(data) > settings.AI_BUDDY_ATTACHMENT_MAX_BYTES:
            raise errors.RequestError(msg='附件超过大小上限')
        if not match_content_type(content_type, _ALLOWED_TYPES):
            raise errors.RequestError(msg=f'不支持的文件类型：{content_type or "未知"}')
        digest = hashlib.sha256(data).hexdigest()
        object_key = f'ai_buddy/attachments/{digest}'
        storage = await require_storage(db=db)
        await write_bytes(db=db, key=object_key, data=data, storage_id=storage.id)
        obj = await ai_buddy_object_service.register_expiring(
            db=db,
            user_id=user_id,
            kind=AIBuddyObjectKind.attachment,
            object_key=object_key,
            storage_id=storage.id,
            size=len(data),
            sha256=digest,
            mime_type=content_type,
        )
        return GetAIBuddyAttachmentDetail.model_validate({
            'object': obj,
            'filename': filename,
            'content_type': content_type,
        })


ai_buddy_attachment_service: AIBuddyAttachmentService = AIBuddyAttachmentService()
