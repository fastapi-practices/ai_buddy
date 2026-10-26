from collections.abc import Sequence
from datetime import datetime
from typing import Literal

import sqlalchemy as sa

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy_crud_plus import CRUDPlus

from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyConversationSurface, AIBuddyConversationView
from backend.plugin.ai_buddy.model import AIBuddyConversation
from backend.plugin.ai_buddy.schema.conversation import CreateAIBuddyConversationParam, UpdateAIBuddyConversationParam
from backend.utils.timezone import timezone


class CRUDAIBuddyConversation(CRUDPlus[AIBuddyConversation]):
    """AI 对话数据库操作类"""

    async def get_latest_by_channel(
        self, db: AsyncSession, user_id: int, channel_id: int
    ) -> AIBuddyConversation | None:
        """
        获取通道中当前用户最近的聊天会话

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param channel_id: 通道 ID
        :return:
        """
        stmt = await self.select(
            user_id=user_id, channel_id=channel_id, surface=AIBuddyConversationSurface.chat, deleted=0
        )
        return (await db.execute(stmt.order_by(self.model.id.desc()).limit(1))).scalar_one_or_none()

    async def get(self, db: AsyncSession, pk: int) -> AIBuddyConversation | None:
        """
        获取对话

        :param db: 数据库会话
        :param pk: ID
        :return:
        """
        return await self.select_model(db, pk, deleted=0)

    async def get_by_conversation_id(self, db: AsyncSession, conversation_id: str) -> AIBuddyConversation | None:
        """
        通过对话 ID 获取对话

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        return await self.select_model_by_column(db, conversation_id=conversation_id, deleted=0)

    async def get_by_ids(
        self, db: AsyncSession, user_id: int, conversation_ids: Sequence[str]
    ) -> Sequence[AIBuddyConversation]:
        """
        查询当前用户在指定范围内未归档的聊天会话

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param conversation_ids: 可访问的对话 ID
        :return:
        """
        if not conversation_ids:
            return []
        return await self.select_models_order(
            db,
            'id',
            'desc',
            user_id=user_id,
            conversation_id__in=list(conversation_ids),
            surface=AIBuddyConversationSurface.chat,
            archived_time__is=None,
            deleted=0,
        )

    async def get_by_conversation_id_for_update(
        self,
        db: AsyncSession,
        conversation_id: str,
    ) -> AIBuddyConversation | None:
        """
        通过对话 ID 获取并锁定对话

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :return:
        """
        stmt = (
            (await self.select(conversation_id=conversation_id, deleted=0))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return await db.scalar(stmt)

    async def get_select(
        self,
        user_id: int,
        *,
        project_id: int | None = None,
        assistant_id: int | None = None,
        q: str | None = None,
        archived: bool = False,
        surface: AIBuddyConversationSurface = AIBuddyConversationSurface.chat,
        view: AIBuddyConversationView | None = None,
        agent_mode: AIBuddyAgentMode | None = None,
    ) -> Select[tuple[AIBuddyConversation]]:
        """
        获取对话列表查询表达式

        :param user_id: 用户 ID
        :param project_id: 项目 ID
        :param assistant_id: 助手 ID
        :param q: 标题关键字
        :param archived: 是否归档
        :param surface: 会话入口
        :param view: 聊天列表视图
        :param agent_mode: 最近一轮模式
        :return:
        """
        filters: dict[str, object] = {'user_id': user_id, 'deleted': 0, 'surface': surface}
        if project_id is not None:
            filters['project_id'] = project_id
        if assistant_id is not None:
            filters['assistant_id'] = assistant_id
        if q:
            filters['title__like'] = f'%{q}%'
        stmt = await self.select(**filters)
        if view is not None or agent_mode is not None:
            stmt = stmt.where(self.model.surface == AIBuddyConversationSurface.chat)
        if view == AIBuddyConversationView.coding:
            stmt = stmt.where(self.model.agent_mode.in_((AIBuddyAgentMode.work, AIBuddyAgentMode.coding)))
        if agent_mode is not None:
            stmt = stmt.where(self.model.agent_mode == agent_mode)
        if archived:
            stmt = stmt.where(self.model.archived_time.is_not(None))
        else:
            stmt = stmt.where(self.model.archived_time.is_(None))
        pin_rank = sa.case((self.model.pinned_time.is_not(None), 1), else_=0)
        activity_time = sa.func.coalesce(
            self.model.last_message_time,
            self.model.updated_time,
            self.model.created_time,
        )
        return stmt.order_by(sa.desc(pin_rank), sa.desc(activity_time), sa.desc(self.model.id))

    async def create(self, db: AsyncSession, obj: CreateAIBuddyConversationParam) -> None:
        """
        创建对话

        :param db: 数据库会话
        :param obj: 创建对话参数
        :return:
        """
        await self.create_model(db, obj)

    async def update(self, db: AsyncSession, pk: int, obj: UpdateAIBuddyConversationParam) -> int:
        """
        更新对话

        :param db: 数据库会话
        :param pk: ID
        :param obj: 更新对话参数
        :return:
        """
        return await self.update_model_by_column(db, obj, id=pk, deleted=0)

    async def update_title(self, db: AsyncSession, pk: int, title: str) -> int:
        """
        更新对话标题

        :param db: 数据库会话
        :param pk: ID
        :param title: 对话标题
        :return:
        """
        return await self.update_model_by_column(db, {'title': title}, id=pk, deleted=0)

    async def update_channel(self, db: AsyncSession, pk: int, channel_id: int) -> int:
        """
        将通道新建会话绑定到来源通道

        :param db: 数据库会话
        :param pk: 会话 ID
        :param channel_id: 通道 ID
        :return:
        """
        return await self.update_model_by_column(db, {'channel_id': channel_id}, id=pk, deleted=0)

    async def update_pinned_time(self, db: AsyncSession, pk: int, pinned_time: datetime | None) -> int:
        """
        更新对话置顶时间

        :param db: 数据库会话
        :param pk: ID
        :param pinned_time: 置顶时间
        :return:
        """
        return await self.update_model_by_column(db, {'pinned_time': pinned_time}, id=pk, deleted=0)

    async def update_archived_time(self, db: AsyncSession, pk: int, archived_time: datetime | None) -> int:
        """
        更新对话归档时间

        :param db: 数据库会话
        :param pk: ID
        :param archived_time: 归档时间
        :return:
        """
        return await self.update_model_by_column(db, {'archived_time': archived_time}, id=pk, deleted=0)

    async def update_source(self, db: AsyncSession, pk: int, source: str) -> int:
        """
        更新对话事实源

        :param db: 数据库会话
        :param pk: ID
        :param source: 事实源
        :return:
        """
        return await self.update_model_by_column(db, {'source': source}, id=pk, deleted=0)

    async def update_workspace(
        self,
        db: AsyncSession,
        pk: int,
        *,
        project_id: int | None,
        assistant_id: int | None,
        goal: str | None,
    ) -> int:
        """
        更新对话工作区字段

        :param db: 数据库会话
        :param pk: ID
        :param project_id: 项目 ID
        :param assistant_id: 助手 ID
        :param goal: 对话目标
        :return:
        """
        return await self.update_model_by_column(
            db,
            {'project_id': project_id, 'assistant_id': assistant_id, 'goal': goal},
            id=pk,
            deleted=0,
        )

    async def clear_project(self, db: AsyncSession, project_id: int) -> int:
        """
        清空指定项目下的对话归属

        :param db: 数据库会话
        :param project_id: 项目 ID
        :return:
        """
        return await self.update_model_by_column(
            db,
            {'project_id': None},
            allow_multiple=True,
            project_id=project_id,
            deleted=0,
        )

    async def clear_assistant(self, db: AsyncSession, assistant_id: int) -> int:
        """
        清空指定助手下的对话绑定

        :param db: 数据库会话
        :param assistant_id: 助手 ID
        :return:
        """
        return await self.update_model_by_column(
            db,
            {'assistant_id': None},
            allow_multiple=True,
            assistant_id=assistant_id,
            deleted=0,
        )

    async def update_last_message(
        self,
        db: AsyncSession,
        pk: int,
        *,
        preview: str | None,
        message_time: datetime | None,
    ) -> int:
        """
        更新对话最后一条消息摘要

        :param db: 数据库会话
        :param pk: ID
        :param preview: 消息预览
        :param message_time: 消息时间
        :return:
        """
        return await self.update_model_by_column(
            db,
            {'last_message_preview': preview, 'last_message_time': message_time},
            id=pk,
            deleted=0,
        )

    async def get_changes(
        self,
        db: AsyncSession,
        user_id: int,
        *,
        after: tuple[datetime, int] | None,
        equal_time: Literal['all', 'after_id', 'none'],
        limit: int,
    ) -> Sequence[AIBuddyConversation]:
        """
        按变更时间读取当前用户的对话变更，已删除的对话作为删除墓碑一并返回

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param after: 游标的变更时间和行 ID，为空时从头读取
        :param equal_time: 与游标变更时间相同的行如何处理：all 都在游标之后，after_id 按行 ID 比较，none 都在游标之前
        :param limit: 返回条数
        :return:
        """
        change_time = sa.func.coalesce(self.model.deleted_time, self.model.updated_time, self.model.created_time)
        stmt = sa.select(self.model).where(self.model.user_id == user_id)
        if after is not None:
            cursor_time, cursor_id = after
            ties = {
                'all': change_time == cursor_time,
                'after_id': sa.and_(change_time == cursor_time, self.model.id > cursor_id),
                'none': sa.false(),
            }
            stmt = stmt.where(sa.or_(change_time > cursor_time, ties[equal_time]))
        return (await db.execute(stmt.order_by(change_time.asc(), self.model.id.asc()).limit(limit))).scalars().all()

    async def delete(self, db: AsyncSession, conversation_id: str, user_id: int) -> int:
        """
        通过对话 ID 删除对话

        :param db: 数据库会话
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :return:
        """
        return await self.delete_model_by_column(
            db,
            logical_deletion=True,
            deleted_flag_column='deleted',
            deleted_flag_value=self.model.id,
            deleted_at_column='deleted_time',
            deleted_at_factory=timezone.now(),
            conversation_id=conversation_id,
            user_id=user_id,
            deleted=0,
        )


ai_buddy_conversation_dao: CRUDAIBuddyConversation = CRUDAIBuddyConversation(AIBuddyConversation)
