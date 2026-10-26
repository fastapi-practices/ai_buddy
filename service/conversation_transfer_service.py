import base64
import itertools

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.core.conf import settings
from backend.database.db import uuid4_str
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.crud.crud_model import ai_buddy_model_dao
from backend.plugin.ai_buddy.crud.crud_provider import ai_buddy_provider_dao
from backend.plugin.ai_buddy.enums import AIBuddyConversationAuditAction, AIBuddyMessageStatus
from backend.plugin.ai_buddy.schema.conversation import CreateAIBuddyConversationParam
from backend.plugin.ai_buddy.schema.conversation_transfer import (
    AIBuddyConversationTransfer,
    AIBuddyConversationTransferInfo,
    AIBuddyConversationTransferMessage,
    GetAIBuddyConversationImportDetail,
)
from backend.plugin.ai_buddy.service.conversation_audit_service import ai_buddy_conversation_audit_service
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.utils.media_store import decode_model_message_payloads, encode_model_message_payloads
from backend.utils.timezone import timezone

_TRANSFER_FORMAT = 'ai-buddy-conversation'
_TRANSFER_MAX_MESSAGES = 2000


async def _validate_inline_media(node: object) -> None:
    """
    导入文档必须自带附件内容，禁止引用对象存储，否则可借还原机制读取他人附件

    :param node: JSON 形态的消息树
    :return:
    """
    if isinstance(node, list):
        for item in node:
            await _validate_inline_media(item)
    elif isinstance(node, dict):
        if node.get('kind') == 'binary':
            data = node.get('data')
            if 'object_key' in node or 'storage_id' in node or not isinstance(data, str):
                raise errors.RequestError(msg='导入文档中的附件必须以内联内容携带')
            if len(data) * 3 // 4 > settings.AI_BUDDY_ATTACHMENT_MAX_BYTES:
                raise errors.RequestError(msg='导入文档中的附件超过大小上限')
            try:
                base64.b64decode(data, validate=True)
            except ValueError as exc:
                raise errors.RequestError(msg='导入文档中的附件不是有效的 base64') from exc
        for value in node.values():
            await _validate_inline_media(value)


class AIBuddyConversationTransferService:
    """AI 会话导入导出服务类，使用与部署无关的 JSON 文档迁移会话"""

    @staticmethod
    async def export_conversation(
        *, db: AsyncSession, user_id: int, conversation_id: str, client: str | None
    ) -> AIBuddyConversationTransfer:
        """
        导出会话，附件以内联内容携带，尚在生成的消息不会导出

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param client: 访问来源
        :return:
        """
        conversation = await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=conversation_id, user_id=user_id
        )
        rows = [
            row
            for row in await ai_buddy_message_dao.get_all_by_message_index(db, conversation_id)
            if row.status != AIBuddyMessageStatus.pending
        ]
        if len(rows) > _TRANSFER_MAX_MESSAGES:
            raise errors.RequestError(msg='会话消息过多，超出单次导出上限')
        try:
            messages = [
                AIBuddyConversationTransferMessage(
                    message_index=row.message_index,
                    role=row.role,
                    origin=row.origin,
                    status=row.status,
                    model_messages=await decode_model_message_payloads(list(row.model_messages)),
                    turn_context=row.turn_context,
                    client_message_id=row.client_message_id,
                    created_time=row.created_time,
                )
                for row in rows
            ]
        except FileNotFoundError as exc:
            raise errors.RequestError(msg='会话中的附件已被清理，无法导出') from exc
        await ai_buddy_conversation_audit_service.record(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
            action=AIBuddyConversationAuditAction.export,
            client=client,
            detail={'messages': len(messages)},
        )
        return AIBuddyConversationTransfer(
            format=_TRANSFER_FORMAT,
            version=1,
            exported_time=timezone.now(),
            conversation=AIBuddyConversationTransferInfo(
                conversation_id=conversation.conversation_id,
                title=conversation.title,
                provider_id=conversation.provider_id,
                model_id=conversation.model_id,
                agent_mode=conversation.agent_mode,
                goal=conversation.goal,
                origin=conversation.origin,
                surface=conversation.surface,
                source=conversation.source,
            ),
            messages=messages,
        )

    async def import_conversation(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        doc: AIBuddyConversationTransfer,
        client: str | None,
    ) -> GetAIBuddyConversationImportDetail:
        """
        导入会话，文档中的对话 ID 未被占用时保留，否则生成新 ID；
        项目、助手等部署内关联不迁移，导入消息以当前时间入库以便其他设备增量同步到

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param doc: 会话文档
        :param client: 访问来源
        :return:
        """
        info = doc.conversation
        indexes = [message.message_index for message in doc.messages]
        if len(indexes) > _TRANSFER_MAX_MESSAGES:
            raise errors.RequestError(msg='会话消息过多，超出单次导入上限')
        if any(left >= right for left, right in itertools.pairwise(indexes)):
            raise errors.RequestError(msg='消息顺序号必须严格递增')
        if any(message.status == AIBuddyMessageStatus.pending for message in doc.messages):
            raise errors.RequestError(msg='不能导入尚在生成的消息')
        for message in doc.messages:
            await _validate_inline_media(message.model_messages)
        if not await ai_buddy_provider_dao.get_visible(db, info.provider_id, user_id):
            raise errors.NotFoundError(msg='文档中的供应商不存在或不可用，请先修改 provider_id 和 model_id')
        if not await ai_buddy_model_dao.get_by_model_and_provider(db, info.model_id, info.provider_id):
            raise errors.NotFoundError(msg='文档中的模型不存在，请先修改 provider_id 和 model_id')

        id_kept = await ai_buddy_conversation_dao.get_by_conversation_id(db, info.conversation_id) is None
        conversation_id = info.conversation_id if id_kept else uuid4_str()
        await ai_buddy_conversation_dao.create(
            db,
            CreateAIBuddyConversationParam(
                conversation_id=conversation_id,
                title=info.title,
                provider_id=info.provider_id,
                model_id=info.model_id,
                user_id=user_id,
                goal=info.goal,
                origin=info.origin,
                surface=info.surface,
                source=info.source,
                agent_mode=info.agent_mode,
            ),
        )
        if doc.messages:
            records: list[dict[str, Any]] = []
            for message in doc.messages:
                original = {'created_time': message.created_time.isoformat()} if message.created_time else {}
                records.append({
                    'conversation_id': conversation_id,
                    'provider_id': info.provider_id,
                    'model_id': info.model_id,
                    'message_index': message.message_index,
                    'role': message.role,
                    'model_messages': await encode_model_message_payloads(
                        message.model_messages, conversation_id=conversation_id, db=db
                    ),
                    'origin': message.origin,
                    'turn_context': {**(message.turn_context or {}), 'imported': original},
                    'status': message.status,
                    'client_message_id': message.client_message_id,
                })
            await ai_buddy_message_dao.bulk_create(db, records)
        await ai_buddy_conversation_service.refresh_last_message(db=db, conversation_id=conversation_id)
        await ai_buddy_conversation_audit_service.record(
            db=db,
            user_id=user_id,
            conversation_id=conversation_id,
            action=AIBuddyConversationAuditAction.import_,
            client=client,
            detail={'messages': len(doc.messages), 'source_conversation_id': info.conversation_id},
        )
        return GetAIBuddyConversationImportDetail(
            conversation_id=conversation_id, id_kept=id_kept, message_count=len(doc.messages)
        )


ai_buddy_conversation_transfer_service: AIBuddyConversationTransferService = AIBuddyConversationTransferService()
