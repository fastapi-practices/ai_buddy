from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exception import errors
from backend.database.db import uuid4_str
from backend.plugin.ai_buddy.agent.work.runs import has_active_run
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.crud.crud_message import ai_buddy_message_dao
from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyOrigin, AIBuddySlashCommand, AIBuddySlashEntry
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatPolishParam
from backend.plugin.ai_buddy.schema.conversation import (
    CreateAIBuddyConversationParam,
    UpdateAIBuddyConversationTitleParam,
)
from backend.plugin.ai_buddy.schema.slash import GetAIBuddySlashCommandDetail, GetAIBuddySlashResultDetail
from backend.plugin.ai_buddy.service.chat_polish_service import ai_buddy_chat_polish_service
from backend.plugin.ai_buddy.service.conversation_service import ai_buddy_conversation_service
from backend.plugin.ai_buddy.utils.conversation_title import normalize_conversation_title
from backend.plugin.ai_buddy.utils.message_converter import (
    expand_message_rows,
    extract_message_preview_text,
    is_user_prompt_message,
)


class AIBuddySlashService:
    """AI 斜杠指令服务类"""

    @staticmethod
    def get_catalog(*, origin: AIBuddySlashEntry) -> list[GetAIBuddySlashCommandDetail]:
        """
        按入口过滤斜杠指令目录

        :param origin: 入口
        :return:
        """
        return [
            GetAIBuddySlashCommandDetail(
                name=item.value,
                description=item.description,
                entries=list(item.entries),
            )
            for item in AIBuddySlashCommand
            if origin in item.entries
        ]

    async def execute(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        command: str,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str | None,
        draft: str | None,
        conversation_scope: Sequence[str] | None = None,
    ) -> GetAIBuddySlashResultDetail:
        """
        执行斜杠指令

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param command: 指令名
        :param origin: 入口
        :param conversation_id: 当前对话 ID
        :param args: 指令参数
        :param draft: 输入框草稿
        :param conversation_scope: IM 当前私聊、群或主题可访问的历史会话
        :return:
        """
        try:
            slash_command = AIBuddySlashCommand(command.strip().lstrip('/').lower())
        except ValueError:
            raise errors.RequestError(msg='当前入口不支持该指令')
        if origin not in slash_command.entries:
            raise errors.RequestError(msg='当前入口不支持该指令')
        if (
            conversation_scope is not None
            and slash_command == AIBuddySlashCommand.switch
            and ((args or '').strip() or conversation_id) not in conversation_scope
        ):
            raise errors.NotFoundError(msg='目标对话不属于当前通道会话')
        if await has_active_run(conversation_id or '') and slash_command not in {
            AIBuddySlashCommand.stop,
            AIBuddySlashCommand.polish,
        }:
            raise errors.ConflictError(msg='生成中途只接受 /stop')

        if slash_command == AIBuddySlashCommand.list:
            return await self._cmd_list(
                db=db,
                user_id=user_id,
                origin=origin,
                conversation_id=conversation_id,
                args=(args or '').strip(),
                draft=draft,
                conversation_scope=conversation_scope,
            )
        handler = getattr(self, f'_cmd_{slash_command.value}')
        return await handler(
            db=db,
            user_id=user_id,
            origin=origin,
            conversation_id=conversation_id,
            args=(args or '').strip(),
            draft=draft,
        )

    async def _cmd_help(
        self,
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
    ) -> GetAIBuddySlashResultDetail:
        """
        列出当前入口可用的斜杠指令

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 指令参数
        :param draft: 输入框草稿
        :return:
        """
        catalog = self.get_catalog(origin=origin)
        lines = [f'/{item.name} {item.description}' for item in catalog]
        return GetAIBuddySlashResultDetail(command='help', message='\n'.join(lines), data={'commands': catalog})

    @staticmethod
    async def _cmd_status(
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
    ) -> GetAIBuddySlashResultDetail:
        """
        查询当前对话和运行状态

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 指令参数
        :param draft: 输入框草稿
        :return:
        """
        if not conversation_id:
            raise errors.RequestError(msg='缺少对话 ID')
        conversation = await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )

        generating = await has_active_run(conversation_id)
        return GetAIBuddySlashResultDetail(
            command='status',
            message='正在生成' if generating else '空闲',
            data={
                'is_generating': generating,
                'origin': conversation.origin,
                'model_id': conversation.model_id,
                'assistant_id': conversation.assistant_id,
                'project_id': conversation.project_id,
            },
        )

    @staticmethod
    async def _cmd_new(
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
    ) -> GetAIBuddySlashResultDetail:
        """
        继承当前对话配置创建新对话

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 指令参数
        :param draft: 输入框草稿
        :return:
        """
        provider_id = None
        model_id = None
        assistant_id = None
        project_id = None
        if conversation_id:
            conversation = await ai_buddy_conversation_service.get_owned_conversation(
                db=db,
                conversation_id=conversation_id,
                user_id=user_id,
            )
            provider_id = conversation.provider_id
            model_id = conversation.model_id
            assistant_id = conversation.assistant_id
            project_id = conversation.project_id
        if provider_id is None or not model_id:
            raise errors.RequestError(msg='新开对话需要已有对话以继承模型')

        new_id = uuid4_str()
        await ai_buddy_conversation_dao.create(
            db,
            CreateAIBuddyConversationParam(
                conversation_id=new_id,
                title='新对话',
                provider_id=provider_id,
                model_id=model_id,
                user_id=user_id,
                assistant_id=assistant_id,
                project_id=project_id,
                origin=origin.value,
            ),
        )
        return GetAIBuddySlashResultDetail(
            command='new',
            message='已新开对话',
            data={'conversation_id': new_id},
        )

    @staticmethod
    async def _cmd_stop(
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
    ) -> GetAIBuddySlashResultDetail:
        """
        停止当前对话的生成任务

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 指令参数
        :param draft: 输入框草稿
        :return:
        """
        if not conversation_id:
            raise errors.RequestError(msg='缺少对话 ID')
        await ai_buddy_conversation_service.stop_generation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        return GetAIBuddySlashResultDetail(command='stop', message='已停止本轮生成', data=None)

    @staticmethod
    async def _cmd_compact(
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
    ) -> GetAIBuddySlashResultDetail:
        """
        删除较早的对话消息并保留最近上下文

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 指令参数
        :param draft: 输入框草稿
        :return:
        """
        if not conversation_id:
            raise errors.RequestError(msg='缺少对话 ID')
        await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        from backend.core.conf import settings

        rows = list(await ai_buddy_message_dao.get_all_by_message_index(db, conversation_id))
        keep = settings.AI_BUDDY_COMPACTION_KEEP_MESSAGES
        if len(rows) <= keep:
            return GetAIBuddySlashResultDetail(
                command='compact',
                message='当前上下文无需压缩',
                data={'conversation_id': conversation_id, 'removed': 0},
            )
        cutoff = rows[-keep].message_index
        removed = await ai_buddy_message_dao.delete_message_index_range(db, conversation_id, 0, cutoff - 1)
        return GetAIBuddySlashResultDetail(
            command='compact',
            message=f'已压缩，删除 {removed} 条较早消息',
            data={'conversation_id': conversation_id, 'removed': removed},
        )

    @staticmethod
    async def _cmd_retry(
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
    ) -> GetAIBuddySlashResultDetail:
        """
        使用上一条用户消息重新生成回复

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 指令参数
        :param draft: 输入框草稿
        :return:
        """
        if not conversation_id:
            raise errors.RequestError(msg='缺少对话 ID')
        state = await ai_buddy_conversation_service.get_chat_state(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            must_exist=True,
            require_messages=True,
        )
        last_user = None
        for row, (start, end) in zip(state.message_rows, state.row_model_message_ranges, strict=False):
            if end <= start:
                continue
            if is_user_prompt_message(message=state.model_messages[start]):
                last_user = row
        if last_user is None:
            raise errors.RequestError(msg='没有可重试的用户消息')
        from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam
        from backend.plugin.ai_buddy.service.chat_service import ai_buddy_chat_service

        context = last_user.turn_context or {}
        if context.get('agent_mode') == AIBuddyAgentMode.coding:
            raise errors.RequestError(msg='编码轮不能通过 /retry 重试，请在桌面重新连接工作区或 ACP Agent 后重新发送')
        prompt = ''
        for message in reversed(state.model_messages):
            if is_user_prompt_message(message=message):
                prompt = extract_message_preview_text(message=message)
                break
        if not prompt:
            raise errors.RequestError(msg='没有可重试的用户消息')
        forwarded = AIBuddyChatForwardedPropsParam(
            provider_id=int(context.get('provider_id') or last_user.provider_id),
            model_id=str(context.get('model_id') or last_user.model_id),
            agent_mode=state.conversation.agent_mode,
        )
        await ai_buddy_chat_service.run_text_prompt(
            user_id=user_id,
            conversation_id=conversation_id,
            prompt=prompt,
            forwarded_props=forwarded,
            origin=AIBuddyOrigin(str(origin)),
        )
        return GetAIBuddySlashResultDetail(
            command='retry',
            message='已用上一条用户消息重跑',
            data={'message_id': last_user.id, 'conversation_id': conversation_id},
        )

    @staticmethod
    async def _cmd_title(
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
    ) -> GetAIBuddySlashResultDetail:
        """
        使用指定标题或最近消息更新对话标题

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 指定标题
        :param draft: 输入框草稿
        :return:
        """
        if not conversation_id:
            raise errors.RequestError(msg='缺少对话 ID')
        title = args
        if not title:
            rows = list(await ai_buddy_message_dao.get_all_by_message_index(db, conversation_id))
            model_messages, _ = await expand_message_rows(rows)
            preview = ''
            for message in reversed(model_messages):
                preview = extract_message_preview_text(message=message)
                if preview:
                    break
            title = normalize_conversation_title(title=preview, fallback='新对话')
        count = await ai_buddy_conversation_service.update(
            db=db,
            conversation_id=conversation_id,
            user_id=user_id,
            obj=UpdateAIBuddyConversationTitleParam(title=title),
        )
        if count <= 0:
            raise errors.RequestError(msg='更新标题失败')
        return GetAIBuddySlashResultDetail(command='title', message='已更新标题', data={'title': title})

    @staticmethod
    async def _cmd_polish(
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
    ) -> GetAIBuddySlashResultDetail:
        """
        润色草稿但不写入对话历史

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 未提供草稿时使用的文本
        :param draft: 输入框草稿
        :return:
        """
        del db, origin, conversation_id
        text = (draft or args or '').strip()
        result = await ai_buddy_chat_polish_service.polish(
            user_id=user_id,
            obj=AIBuddyChatPolishParam(text=text),
        )
        return GetAIBuddySlashResultDetail(
            command='polish',
            message='已润色草稿，未写入历史',
            data={'draft': result.text},
        )

    @staticmethod
    async def _cmd_list(
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
        conversation_scope: Sequence[str] | None = None,
    ) -> GetAIBuddySlashResultDetail:
        """
        列出当前用户可切换的对话

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 指令参数
        :param draft: 输入框草稿
        :param conversation_scope: 当前通道会话允许访问的对话 ID
        :return:
        """
        if conversation_scope is None:
            page = await ai_buddy_conversation_service.get_list(db=db, user_id=user_id)
            items = page.get('items') or []
        else:
            rows = await ai_buddy_conversation_dao.get_by_ids(db, user_id, conversation_scope)
            items = [{'conversation_id': row.conversation_id, 'title': row.title} for row in rows]
        lines = [f'{item.get("conversation_id")} {item.get("title")}' for item in items[:20]]
        return GetAIBuddySlashResultDetail(
            command='list',
            message='\n'.join(lines) or '暂无对话',
            data={'items': items[:20]},
        )

    @staticmethod
    async def _cmd_switch(
        *,
        db: AsyncSession,
        user_id: int,
        origin: AIBuddySlashEntry,
        conversation_id: str | None,
        args: str,
        draft: str | None,
    ) -> GetAIBuddySlashResultDetail:
        """
        校验并返回要切换的对话

        :param db: 数据库会话
        :param user_id: 用户 ID
        :param origin: 指令入口
        :param conversation_id: 当前对话 ID
        :param args: 目标对话 ID
        :param draft: 输入框草稿
        :return:
        """
        target = args or conversation_id
        if not target:
            raise errors.RequestError(msg='缺少要切换的对话 ID')
        conversation = await ai_buddy_conversation_service.get_owned_conversation(
            db=db,
            conversation_id=target,
            user_id=user_id,
        )
        return GetAIBuddySlashResultDetail(
            command='switch',
            message='已切换对话',
            data={'conversation_id': conversation.conversation_id, 'title': conversation.title},
        )


ai_buddy_slash_service: AIBuddySlashService = AIBuddySlashService()
