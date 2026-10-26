from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.enums import AIBuddyConversationAuditAction
from backend.plugin.ai_buddy.model.conversation import AIBuddyConversation
from backend.plugin.ai_buddy.model.message import AIBuddyMessage
from backend.plugin.ai_buddy.schema.sync import GetAIBuddySyncChangeDetail, GetAIBuddySyncDetail
from backend.plugin.ai_buddy.service.conversation_audit_service import ai_buddy_conversation_audit_service
from backend.utils.timezone import timezone

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
# 对话排在同一变更时间的消息之前，游标按（变更时间, 实体序, 行 ID）整体排序
_RANK_CONVERSATION = 0
_RANK_MESSAGE = 1
# 数据库时间精度可能只到秒，追平后回退该时长重读，避免遗漏同秒写入
_CATCH_UP_OVERLAP = timedelta(seconds=2)


def _encode_cursor(*, change_time: datetime, rank: int, row_id: int) -> str:
    micros = (change_time.astimezone(UTC) - _EPOCH) // timedelta(microseconds=1)
    return f'{micros}.{rank}.{row_id}'


def _decode_cursor(cursor: str) -> tuple[datetime, int, int]:
    micros, rank, row_id = cursor.split('.')
    return _EPOCH + timedelta(microseconds=int(micros)), int(rank), int(row_id)


def _change_time(row: AIBuddyConversation | AIBuddyMessage) -> datetime:
    return row.deleted_time or row.updated_time or row.created_time


class AIBuddySyncService:
    """AI 会话同步服务类，提供跨设备增量拉取，删除以墓碑形式同步"""

    @staticmethod
    async def get_changes(
        *, db: AsyncSession, user_id: int, cursor: str | None, limit: int, client: str | None
    ) -> GetAIBuddySyncDetail:
        """
        拉取游标之后的对话和消息变更，按（变更时间, 实体序, 行 ID）升序

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param cursor: 同步游标，首次同步为空
        :param limit: 本次最多返回条数
        :param client: 访问来源，首次同步时写入审计
        :return:
        """
        if cursor is None:
            # 不带游标代表一台设备从头开始同步，记录跨设备访问；增量轮询不记录
            await ai_buddy_conversation_audit_service.record(
                db=db,
                user_id=user_id,
                conversation_id='*',
                action=AIBuddyConversationAuditAction.sync,
                client=client,
            )
        after = _decode_cursor(cursor) if cursor else None
        ties: dict[int, Literal['all', 'after_id', 'none']] = {
            _RANK_CONVERSATION: 'none' if after and after[1] > _RANK_CONVERSATION else 'after_id',
            _RANK_MESSAGE: 'all' if after and after[1] < _RANK_MESSAGE else 'after_id',
        }
        key = (after[0], after[2]) if after else None
        conversations = await ai_buddy_conversation_dao.get_changes(
            db, user_id, after=key, equal_time=ties[_RANK_CONVERSATION], limit=limit + 1
        )
        messages = await ai_buddy_message_dao.get_changes(
            db, user_id, after=key, equal_time=ties[_RANK_MESSAGE], limit=limit + 1
        )
        merged = sorted(
            [(_change_time(row), _RANK_CONVERSATION, row) for row in conversations]
            + [(_change_time(row), _RANK_MESSAGE, row) for row in messages],
            key=lambda item: (item[0], item[1], item[2].id),
        )
        page = merged[:limit]
        has_more = len(merged) > limit
        changes = [
            GetAIBuddySyncChangeDetail(
                entity='conversation' if rank == _RANK_CONVERSATION else 'message',
                row_id=row.id,
                conversation_id=row.conversation_id,
                change='delete' if row.deleted else 'upsert',
                change_time=changed,
                message_index=getattr(row, 'message_index', None),
                role=getattr(row, 'role', None),
                status=getattr(row, 'status', None),
                client_message_id=getattr(row, 'client_message_id', None),
                title=getattr(row, 'title', None),
                revision=getattr(row, 'revision', None),
                source=getattr(row, 'source', None),
            )
            for changed, rank, row in page
        ]
        if has_more:
            changed, rank, row = page[-1]
            next_cursor = _encode_cursor(change_time=changed, rank=rank, row_id=row.id)
        else:
            tail = page[-1][0] if page else (after[0] if after else timezone.now())
            next_cursor = _encode_cursor(
                change_time=min(tail, timezone.now() - _CATCH_UP_OVERLAP), rank=_RANK_CONVERSATION, row_id=0
            )
        return GetAIBuddySyncDetail(changes=changes, next_cursor=next_cursor, has_more=has_more)


ai_buddy_sync_service: AIBuddySyncService = AIBuddySyncService()
