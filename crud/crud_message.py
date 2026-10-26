from collections.abc import Sequence
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, and_, false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.enums import AIBuddyMessageStatus
from backend.plugin.ai_buddy.model import AIBuddyMessage
from backend.plugin.ai_buddy.model.conversation import AIBuddyConversation
from backend.utils.timezone import timezone


class CRUDAIBuddyMessage(CRUDPlus[AIBuddyMessage]):
    """AI 消息数据库操作类"""

    async def get_file_understanding_cache(self, db: AsyncSession, conversation_id: str) -> dict[str, Any]:
        """读取当前分支最近保存的文件理解缓存

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        context = await db.scalar(
            select(self.model.turn_context)
            .where(
                self.model.conversation_id == conversation_id,
                self.model.deleted == 0,
                self.model.turn_context['file_understanding'].as_string().is_not(None),
            )
            .order_by(self.model.message_index.desc(), self.model.id.desc())
            .limit(1)
        )
        return (context or {}).get('file_understanding', {})

    async def get_user_anchor(self, db: AsyncSession, message: AIBuddyMessage) -> AIBuddyMessage | None:
        """将助手片段定位到所属用户轮

        :param db: 数据库会话
        :param message: 消息内容
        :return:
        """
        if message.role == 'user':
            return message
        return await db.scalar(
            select(self.model)
            .where(
                self.model.conversation_id == message.conversation_id,
                self.model.deleted == 0,
                self.model.role == 'user',
                self.model.message_index <= message.message_index,
            )
            .order_by(self.model.message_index.desc(), self.model.id.desc())
            .limit(1)
        )

    async def consume_pending_branch(self, db: AsyncSession, conversation_id: str) -> dict[str, Any] | None:
        """将截断在首条用户输入之前的分支锚点交给下一条用户消息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        marker = await db.scalar(
            select(self.model)
            .where(
                self.model.conversation_id == conversation_id,
                self.model.deleted == 0,
                self.model.role == 'system',
                self.model.turn_context['branch_pending'].as_boolean().is_(True),
            )
            .order_by(self.model.message_index.desc(), self.model.id.desc())
            .limit(1)
        )
        if marker is None:
            return None
        branch = (marker.turn_context or {}).get('branch')
        await self.delete_message(db, marker.id)
        return branch

    async def get_history_page(
        self, db: AsyncSession, conversation_id: str, *, before: tuple[int, int] | None, limit: int
    ) -> Sequence[AIBuddyMessage]:
        """按稳定复合游标读取历史，返回倒序数据库行

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param before: 游标之前的消息 ID
        :param limit: 数量上限
        :return:
        """
        query = select(self.model).where(self.model.conversation_id == conversation_id, self.model.deleted == 0)
        if before is not None:
            index, pk = before
            query = query.where(
                or_(self.model.message_index < index, and_(self.model.message_index == index, self.model.id < pk))
            )
        result = await db.scalars(query.order_by(self.model.message_index.desc(), self.model.id.desc()).limit(limit))
        return result.all()

    async def get_branch_versions(
        self, db: AsyncSession, *, user_id: int, conversation_id: str, message_id: int
    ) -> Sequence[tuple[AIBuddyMessage, AIBuddyConversation]]:
        """只读取当前用户的同源会话版本

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_id: 对话 ID
        :param message_id: 消息 ID
        :return:
        """
        branch = self.model.turn_context['branch']
        result = await db.execute(
            select(self.model, AIBuddyConversation)
            .join(AIBuddyConversation, AIBuddyConversation.conversation_id == self.model.conversation_id)
            .where(
                self.model.deleted == 0,
                AIBuddyConversation.deleted == 0,
                AIBuddyConversation.user_id == user_id,
                branch['source_conversation_id'].as_string() == conversation_id,
                branch['source_message_id'].as_integer() == message_id,
            )
            .order_by(AIBuddyConversation.created_time.asc(), self.model.id.asc())
        )
        return result.all()

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyMessage | None:
        """
        获取消息

        :param db: 数据库会话
        :param pk: ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_select(self, conversation_id: str) -> Select:
        """
        获取对话消息查询表达式

        :param conversation_id: 对话 ID
        :return:
        """
        return await self.select_order('id', 'asc', conversation_id=conversation_id, deleted=0)

    async def get_all(self, db: AsyncSession, conversation_id: str) -> Sequence[AIBuddyMessage]:
        """
        获取对话所有消息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        return await self.select_models_order(db, 'id', 'asc', conversation_id=conversation_id, deleted=0)

    async def get_all_by_message_index(self, db: AsyncSession, conversation_id: str) -> Sequence[AIBuddyMessage]:
        """
        按聊天上下文顺序获取对话所有消息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        return await self.select_models_order(
            db,
            ['message_index', 'id'],
            ['asc', 'asc'],
            conversation_id=conversation_id,
            deleted=0,
        )

    async def get_by_client_message_id(
        self, db: AsyncSession, conversation_id: str, client_message_id: str
    ) -> AIBuddyMessage | None:
        """
        通过客户端消息 ID 获取已提交的消息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param client_message_id: 客户端消息 ID
        :return:
        """
        stmt = (
            select(self.model)
            .where(
                self.model.conversation_id == conversation_id,
                self.model.client_message_id == client_message_id,
                self.model.deleted == 0,
            )
            .order_by(self.model.id.desc())
            .limit(1)
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    async def get_changes(
        self,
        db: AsyncSession,
        user_id: int,
        *,
        after: tuple[datetime, int] | None,
        equal_time: Literal['all', 'after_id', 'none'],
        limit: int,
    ) -> Sequence[AIBuddyMessage]:
        """
        按变更时间读取当前用户全部对话下的消息变更，已删除的消息作为删除墓碑一并返回

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param after: 游标的变更时间和行 ID，为空时从头读取
        :param equal_time: 与游标变更时间相同的行如何处理：all 都在游标之后，after_id 按行 ID 比较，none 都在游标之前
        :param limit: 返回条数
        :return:
        """
        change_time = func.coalesce(self.model.deleted_time, self.model.updated_time, self.model.created_time)
        stmt = select(self.model).join(
            AIBuddyConversation, AIBuddyConversation.conversation_id == self.model.conversation_id
        )
        stmt = stmt.where(AIBuddyConversation.user_id == user_id)
        if after is not None:
            cursor_time, cursor_id = after
            ties = {
                'all': change_time == cursor_time,
                'after_id': and_(change_time == cursor_time, self.model.id > cursor_id),
                'none': false(),
            }
            stmt = stmt.where(or_(change_time > cursor_time, ties[equal_time]))
        return (await db.execute(stmt.order_by(change_time.asc(), self.model.id.asc()).limit(limit))).scalars().all()

    async def get_next_message_index(self, db: AsyncSession, conversation_id: str) -> int:
        """
        获取下一条消息索引

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        rows = await self.select_models_order(
            db,
            'message_index',
            'desc',
            conversation_id=conversation_id,
            deleted=0,
            limit=1,
        )
        return (rows[0].message_index if rows else -1) + 1

    async def get_pending(self, db: AsyncSession, conversation_id: str) -> Sequence[AIBuddyMessage]:
        """
        获取对话中未完成的生成消息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        return await self.select_models(
            db,
            conversation_id=conversation_id,
            status=AIBuddyMessageStatus.pending,
            deleted=0,
        )

    async def get_stale_pending(self, db: AsyncSession, before: datetime) -> Sequence[AIBuddyMessage]:
        """
        获取超过指定时间仍未完成的生成消息

        :param db: 数据库会话
        :param before: 最后更新时间上限
        :return:
        """
        result = await db.scalars(
            select(self.model).where(
                self.model.status == AIBuddyMessageStatus.pending,
                self.model.deleted == 0,
                func.coalesce(self.model.updated_time, self.model.created_time) < before,
            )
        )
        return result.all()

    async def create(self, db: AsyncSession, obj: dict[str, Any]) -> AIBuddyMessage:
        """
        创建单条消息并返回 ORM 对象

        :param db: 数据库会话
        :param obj: 消息字段
        :return:
        """
        message = self.model(**obj)
        db.add(message)
        await db.flush()
        return message

    async def bulk_create(self, db: AsyncSession, objs: list[dict[str, Any]]) -> None:
        """
        批量创建消息

        :param db: 数据库会话
        :param objs: 消息列表
        :return:
        """
        now = timezone.now()
        payloads = [
            {
                **obj,
                'created_time': obj.get('created_time', now),
                'updated_time': obj.get('updated_time'),
            }
            for obj in objs
        ]
        await self.bulk_create_models(db, payloads)

    async def update_message_indexes_offset(
        self,
        db: AsyncSession,
        conversation_id: str,
        start_message_index: int,
        offset: int,
    ) -> int:
        """
        平移指定索引及之后的消息索引

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param start_message_index: 起始消息索引
        :param offset: 平移偏移量
        :return:
        """
        if offset == 0:
            return 0
        result = await db.execute(
            update(self.model)
            .where(
                self.model.conversation_id == conversation_id,
                self.model.message_index >= start_message_index,
                self.model.deleted == 0,
            )
            .values(message_index=self.model.message_index + offset)
        )
        return result.rowcount or 0

    async def update(self, db: AsyncSession, pk: int, obj: dict[str, Any]) -> int:
        """
        更新消息

        :param db: 数据库会话
        :param pk: 消息 ID
        :param obj: 更新内容
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def update_pending(self, db: AsyncSession, pk: int, obj: dict[str, Any]) -> int:
        """
        更新仍处于待生成状态的消息

        :param db: 数据库会话
        :param pk: 消息 ID
        :param obj: 更新字段
        :return:
        """
        return await self.update_model_by_column(
            db,
            obj,
            id=pk,
            status=AIBuddyMessageStatus.pending,
            deleted=0,
        )

    async def delete_pending(self, db: AsyncSession, pk: int) -> int:
        """
        删除待生成消息

        :param db: 数据库会话
        :param pk: 消息 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id=pk,
            status=AIBuddyMessageStatus.pending,
            deleted=0,
        )

    async def delete_message_index_range(
        self,
        db: AsyncSession,
        conversation_id: str,
        start_message_index: int,
        end_message_index: int,
    ) -> int:
        """
        按消息索引范围逻辑删除消息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param start_message_index: 起始消息索引
        :param end_message_index: 结束消息索引
        :return:
        """
        return await self.delete_model_by_column(
            db,
            allow_multiple=True,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            conversation_id=conversation_id,
            message_index__ge=start_message_index,
            message_index__le=end_message_index,
            deleted=0,
        )

    async def delete_message(self, db: AsyncSession, pk: int) -> int:
        """
        删除指定消息

        :param db: 数据库会话
        :param pk: 消息 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            id=pk,
            deleted=0,
        )

    async def delete(self, db: AsyncSession, conversation_id: str) -> int:
        """
        删除对话所有消息

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            allow_multiple=True,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            conversation_id=conversation_id,
            deleted=0,
        )


ai_buddy_message_dao: CRUDAIBuddyMessage = CRUDAIBuddyMessage(AIBuddyMessage)
