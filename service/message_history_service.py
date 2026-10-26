import asyncio
import base64
import json

from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.crud.crud_message_error import ai_buddy_message_error_dao
from backend.plugin.ai_buddy.enums import AIBuddyMessageRole, AIBuddyMessageStatus
from backend.plugin.ai_buddy.model.message import AIBuddyMessage
from backend.plugin.ai_buddy.schema.chat_message import AIBuddyChatAgUiMessagesSnapshotDetail
from backend.plugin.ai_buddy.schema.message_history import (
    GetAIBuddyMessagePageDetail,
    GetAIBuddyMessageSearchDetail,
    GetAIBuddyMessageSearchItem,
    GetAIBuddyMessageVersionDetail,
    GetAIBuddyPlanDetail,
)
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.utils.message_converter import expand_message_row_metadata, expand_message_rows
from backend.plugin.ai_buddy.utils.message_snapshot import serialize_messages_to_snapshot
from backend.plugin.ai_buddy.utils.plan_store import get_plan_store


class AIBuddyMessageHistoryService:
    """历史检索、分支版本与计划读取"""

    async def page(
        self, *, db: AsyncSession, conversation_id: str, user_id: int, before: str | None, limit: int
    ) -> GetAIBuddyMessagePageDetail:
        """
        读取最近一页或指定游标之前的消息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param before: 上一页游标
        :param limit: 返回条数
        :return:
        """
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=conversation_id, user_id=user_id
        )
        rows = list(
            await ai_buddy_message_dao.get_history_page(
                db, conversation_id, before=self._decode_cursor(cursor=before), limit=limit + 1
            )
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        snapshot = await self._serialize_rows(db=db, conversation_id=conversation_id, rows=list(reversed(page)))
        return GetAIBuddyMessagePageDetail(
            messages_snapshot=snapshot,
            has_more=has_more,
            next_cursor=self.encode_cursor(row=page[-1]) if has_more and page else None,
        )

    async def search(
        self, *, db: AsyncSession, conversation_id: str, user_id: int, q: str, cursor: str | None, limit: int
    ) -> GetAIBuddyMessageSearchDetail:
        """
        搜索全部历史，单次最多扫描 500 行并返回可继续的游标

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param q: 搜索关键词
        :param cursor: 分页游标
        :param limit: 返回条数
        :return:
        """
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=conversation_id, user_id=user_id
        )
        needle = q.strip().casefold()
        if not needle:
            raise errors.RequestError(msg='搜索内容不能为空')
        before = self._decode_cursor(cursor=cursor)
        items: list[GetAIBuddyMessageSearchItem] = []
        scanned = 0
        last = None
        while scanned < 500:
            rows = await ai_buddy_message_dao.get_history_page(db, conversation_id, before=before, limit=51)
            for row in rows[:50]:
                last = row
                scanned += 1
                candidate = self._snapshot_text(value=row.model_messages) + json.dumps(
                    row.model_messages, ensure_ascii=False
                )
                if (
                    row.model_messages
                    and row.status == AIBuddyMessageStatus.success
                    and needle not in candidate.casefold()
                ):
                    continue
                snapshot = await self._serialize_rows(db=db, conversation_id=conversation_id, rows=[row])
                payload = snapshot.model_dump(by_alias=True)
                for message in payload.get('messages', []):
                    text = self._snapshot_text(value=message)
                    position = text.casefold().find(needle)
                    if position < 0:
                        continue
                    items.append(
                        GetAIBuddyMessageSearchItem(
                            message_id=row.id,
                            snapshot_id=message['id'],
                            message_index=row.message_index,
                            role=message['role'],
                            text=text,
                            excerpt=text[max(0, position - 80) : position + len(q) + 160],
                        )
                    )
                    break
                if len(items) >= limit:
                    more = row is not rows[-1]
                    return GetAIBuddyMessageSearchDetail(
                        items=items, has_more=more, next_cursor=self.encode_cursor(row=row) if more else None
                    )
            if len(rows) <= 50:
                return GetAIBuddyMessageSearchDetail(items=items, has_more=False)
            assert last is not None
            before = (last.message_index, last.id)
        assert last is not None
        return GetAIBuddyMessageSearchDetail(items=items, has_more=True, next_cursor=self.encode_cursor(row=last))

    @staticmethod
    async def plan(*, db: AsyncSession, conversation_id: str, user_id: int) -> GetAIBuddyPlanDetail:
        """
        读取代理实际保存的计划

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :return:
        """
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=conversation_id, user_id=user_id
        )
        items = await get_plan_store(user_id=user_id, conversation_id=conversation_id).get_items()
        return GetAIBuddyPlanDetail(items=[item.model_dump(mode='json') for item in items])

    @staticmethod
    async def versions(
        *, db: AsyncSession, conversation_id: str, user_id: int, message_id: int
    ) -> list[GetAIBuddyMessageVersionDetail]:
        """
        枚举当前用户可访问的同源分支，不覆盖旧回复

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 当前用户 ID
        :param message_id: 消息 ID
        :return:
        """
        current = await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=conversation_id, user_id=user_id
        )
        assert current is not None
        message = await ai_buddy_message_dao.get(db, message_id)
        if message is None or message.conversation_id != conversation_id:
            raise errors.NotFoundError(msg='消息不存在')
        message = await ai_buddy_message_dao.get_user_anchor(db, message) or message
        branch = (message.turn_context or {}).get('branch', {})
        source_id = branch.get('source_conversation_id', conversation_id)
        source_message = branch.get('source_message_id', message.id)
        source = await ai_buddy_conversation_service.get_owned_conversation(
            db=db, conversation_id=source_id, user_id=user_id, must_exist=False
        )
        result = []
        if source is not None:
            result.append(
                GetAIBuddyMessageVersionDetail(
                    conversation_id=source_id,
                    title=source.title,
                    created_time=source.created_time,
                    message_id=source_message,
                    source_conversation_id=source_id,
                    source_message_id=source_message,
                )
            )
        branches = await ai_buddy_message_dao.get_branch_versions(
            db, user_id=user_id, conversation_id=source_id, message_id=source_message
        )
        seen = {item.conversation_id for item in result}
        for row, conversation in branches:
            if conversation.conversation_id in seen:
                continue
            seen.add(conversation.conversation_id)
            result.append(
                GetAIBuddyMessageVersionDetail(
                    conversation_id=conversation.conversation_id,
                    title=conversation.title,
                    created_time=conversation.created_time,
                    message_id=row.id if row.role != AIBuddyMessageRole.system else None,
                    source_conversation_id=source_id,
                    source_message_id=source_message,
                )
            )
        if current.conversation_id not in seen:
            result.append(
                GetAIBuddyMessageVersionDetail(
                    conversation_id=current.conversation_id,
                    title=current.title,
                    created_time=current.created_time,
                    message_id=message_id,
                    source_conversation_id=source_id,
                    source_message_id=source_message,
                )
            )
        return result

    @staticmethod
    def encode_cursor(*, row: AIBuddyMessage) -> str:
        """
        复合顺序游标不依赖连续主键

        :param row: 消息记录
        :return:
        """
        return base64.urlsafe_b64encode(json.dumps([row.message_index, row.id]).encode()).decode().rstrip('=')

    @staticmethod
    def _decode_cursor(*, cursor: str | None) -> tuple[int, int] | None:
        """
        验证不透明历史游标

        :param cursor: 分页游标
        :return:
        """
        if cursor is None:
            return None
        try:
            if len(cursor) > 128:
                raise ValueError
            value = json.loads(base64.b64decode(cursor + '=' * (-len(cursor) % 4), altchars=b'-_', validate=True))
            if not isinstance(value, list) or len(value) != 2:
                raise ValueError
            if any(type(item) is not int or item < 0 for item in value) or value[1] == 0:
                raise ValueError
            return value[0], value[1]
        except (ValueError, TypeError, UnicodeError) as exc:
            raise errors.RequestError(msg='历史消息游标无效') from exc

    @staticmethod
    async def _serialize_rows(
        *, db: AsyncSession, conversation_id: str, rows: Sequence[AIBuddyMessage]
    ) -> AIBuddyChatAgUiMessagesSnapshotDetail:
        """
        历史分页与详情共用原生消息快照编码

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param rows: 记录列表
        :return:
        """
        messages, ranges = await expand_message_rows(list(rows))
        message_ids, provider_ids, model_ids, indexes, contexts = expand_message_row_metadata(rows, ranges)
        error_rows = await ai_buddy_message_error_dao.get_all_by_message_ids(db, [row.id for row in rows])
        error_map = {row.message_id: (row.message, row.detail) for row in error_rows}
        fallbacks = [
            {
                'message_id': row.id,
                'conversation_id': row.conversation_id,
                'provider_id': row.provider_id,
                'model_id': row.model_id,
                'message_index': row.message_index,
                'created_time': row.created_time,
            }
            for row, (start, end) in zip(rows, ranges, strict=False)
            if start == end and row.id in error_map
        ]
        return await asyncio.to_thread(
            serialize_messages_to_snapshot,
            messages,
            conversation_id=conversation_id,
            message_ids=message_ids,
            provider_ids=provider_ids,
            model_ids=model_ids,
            message_indexes=indexes,
            turn_contexts=contexts,
            errors=error_map,
            error_fallbacks=fallbacks,
        )

    def _snapshot_text(self, *, value: Any) -> str:
        """
        搜索展示文本，跳过媒体载荷和内部元数据

        :param value: 消息快照内容
        :return:
        """
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return '\n'.join(filter(None, (self._snapshot_text(value=item) for item in value)))
        if isinstance(value, dict):
            return '\n'.join(
                self._snapshot_text(value=value[key])
                for key in ('content', 'text', 'reasoning', 'parts', 'toolCalls', 'function', 'arguments')
                if key in value
            )
        return ''


ai_buddy_message_history_service = AIBuddyMessageHistoryService()
