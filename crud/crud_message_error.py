from collections.abc import Sequence
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.model import AIBuddyMessageError
from backend.utils.timezone import timezone


class CRUDAIBuddyMessageError(CRUDPlus[AIBuddyMessageError]):
    """AI 消息错误数据库操作类"""

    async def get_by_message_id(self, db: AsyncSession, message_id: int) -> AIBuddyMessageError | None:
        """
        通过消息 ID 获取错误

        :param db: 数据库会话
        :param message_id: 消息 ID
        :return:
        """
        return await self.select_model_by_column(db, message_id=message_id, deleted=0)

    async def get_all_by_message_ids(
        self,
        db: AsyncSession,
        message_ids: Sequence[int],
    ) -> Sequence[AIBuddyMessageError]:
        """
        通过消息 ID 列表获取错误

        :param db: 数据库会话
        :param message_ids: 消息 ID 列表
        :return:
        """
        if not message_ids:
            return []
        return await self.select_models(db, message_id__in=list(message_ids), deleted=0)

    async def create(self, db: AsyncSession, obj: dict[str, Any]) -> AIBuddyMessageError:
        """
        创建消息错误

        :param db: 数据库会话
        :param obj: 错误字段
        :return:
        """
        error = self.model(**obj)
        db.add(error)
        await db.flush()
        return error

    async def upsert(self, db: AsyncSession, obj: dict[str, Any]) -> AIBuddyMessageError:
        """
        按消息 ID 写入或更新错误

        使用 PostgreSQL 内置的 INSERT ... ON CONFLICT DO UPDATE，
        单条语句完成写入与更新，避免先查询再写入的竞态

        :param db: 数据库会话
        :param obj: 错误字段
        :return:
        """
        now = timezone.now()
        payload = {**obj, 'created_time': now}
        insert_stmt = insert(self.model).values(**payload)
        update_values = {
            key: insert_stmt.excluded[key] for key in payload if key not in ('message_id', 'deleted', 'created_time')
        }
        update_values['updated_time'] = now
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=['message_id', 'deleted'],
            set_=update_values,
        ).returning(self.model)
        result = await db.execute(stmt)
        return result.scalars().one()

    async def delete_by_message_ids(self, db: AsyncSession, message_ids: Sequence[int]) -> int:
        """
        按消息 ID 列表删除错误

        :param db: 数据库会话
        :param message_ids: 消息 ID 列表
        :return:
        """
        if not message_ids:
            return 0
        return await self.delete_model_by_column(
            db,
            allow_multiple=True,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            message_id__in=list(message_ids),
            deleted=0,
        )

    async def delete_by_conversation_id(self, db: AsyncSession, conversation_id: str) -> int:
        """
        删除对话下所有错误

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


ai_buddy_message_error_dao: CRUDAIBuddyMessageError = CRUDAIBuddyMessageError(AIBuddyMessageError)
