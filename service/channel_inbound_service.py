import hashlib

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse
from starlette_context import request_cycle_context

from backend.app.admin.crud.crud_user import user_dao
from backend.common.enums import StatusType
from backend.common.exception import errors
from backend.database.db import async_db_session, uuid4_str
from backend.plugin.ai_buddy.agent.work.runs import attach_event_stream
from backend.plugin.ai_buddy.channels.adapters import parse_channel_payload
from backend.plugin.ai_buddy.channels.stream import filter_channel_stream
from backend.plugin.ai_buddy.channels.types import InboundMessage
from backend.plugin.ai_buddy.crud.crud_channel import ai_buddy_channel_dao
from backend.plugin.ai_buddy.crud.crud_channel_user import ai_buddy_channel_user_dao
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.enums import (
    AIBuddyChannelType,
    AIBuddyConversationSurface,
    AIBuddyModelKind,
    AIBuddyOrigin,
    AIBuddySlashEntry,
)
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam
from backend.plugin.ai_buddy.schema.conversation import CreateAIBuddyConversationParam
from backend.plugin.ai_buddy.service.chat_service import ai_buddy_chat_service
from backend.plugin.ai_buddy.service.default_model_service import ai_buddy_default_model_service
from backend.plugin.ai_buddy.service.slash_service import ai_buddy_slash_service


@contextmanager
def _channel_request_context(data: dict[str, Any]) -> Generator[None, None, None]:
    """确保通道后台异常时也恢复 starlette 请求上下文

    :param data: 输入数据
    :return:
    """
    failure: BaseException | None = None
    with request_cycle_context(data):
        try:
            yield
        except BaseException as exc:
            failure = exc
    if failure is not None:
        raise failure


class AIBuddyChannelInboundService:
    """通道入站服务"""

    async def handle_inbound(  # ruff: ignore[complex-structure]
        self,
        *,
        pk: int,
        user_id: int,
        payload: dict[str, Any] | None = None,
        inbound: InboundMessage | None = None,
    ) -> dict[str, Any] | StreamingResponse:
        """
        通道入站归一为 conversation + 用户消息 + origin=im

        Discord 转发保留原生消息字段，接收机器人 ID 由 config.bot_id 或受认证载荷 bot_id 提供

        :param pk: 通道 ID
        :param user_id: 通道所属用户
        :param payload: 原始载荷
        :param inbound: 已由原生 SDK 校验并归一的消息
        :return:
        """
        async with async_db_session.begin() as db:
            channel = await ai_buddy_channel_dao.get_for_update(db, pk)
            if channel is None or channel.user_id != user_id:
                raise errors.NotFoundError(msg='通道不存在')
            if channel.status != StatusType.enable:
                raise errors.RequestError(msg='通道已停用')
            channel_type = AIBuddyChannelType(channel.type)
            if inbound is None:
                payload = payload or {}
                if channel_type == AIBuddyChannelType.discord:
                    message, ignored_reason = self._filter_discord_inbound(payload=payload, config=channel.config or {})
                    if message is None:
                        return {'ignored': True, 'reason': ignored_reason}
                    payload = message
                inbound = parse_channel_payload(channel_type, payload)
            if not inbound.text.strip() or not inbound.external_id.strip():
                raise errors.RequestError(msg='通道消息缺少文字或发送者标识')
            mapping = await ai_buddy_channel_user_dao.get_by_external_id(db, channel.id, inbound.external_id)
            mapped_user_id = mapping.user_id if mapping is not None else channel.user_id
            if mapping is None:
                mapping = await ai_buddy_channel_user_dao.create(db, channel.id, mapped_user_id, inbound.external_id)
            session_mapping = mapping
            if inbound.session_id:
                session_key = f'session:{hashlib.sha256(inbound.session_id.encode()).hexdigest()}'
                session_mapping = await ai_buddy_channel_user_dao.get_by_external_id(db, channel.id, session_key)
                if session_mapping is None:
                    session_mapping = await ai_buddy_channel_user_dao.create(
                        db, channel.id, mapped_user_id, session_key
                    )
                mapped_user_id = session_mapping.user_id
            user = await user_dao.get(db, mapped_user_id)
            if user is None or user.deleted or user.status != StatusType.enable:
                raise errors.RequestError(msg='通道用户已停用或删除')
            user_context = {
                'user_id': mapped_user_id,
                'is_superuser': bool(user.is_superuser),
                'language': 'zh-CN',
            }
            with _channel_request_context(user_context):
                bound_id = (session_mapping.extra or {}).get('conversation_id')
                conversation = (
                    await ai_buddy_conversation_dao.get_by_conversation_id(db, str(bound_id)) if bound_id else None
                )
                if (
                    conversation is None
                    and not bound_id
                    and inbound.session_id is None
                    and channel_type == AIBuddyChannelType.wechat
                ):
                    bound_user = str((channel.config or {}).get('ilink_user_id') or '')
                    if bound_user and inbound.external_id == bound_user:
                        conversation = await ai_buddy_conversation_dao.get_latest_by_channel(
                            db, mapped_user_id, channel.id
                        )
                if conversation is not None and (
                    conversation.user_id != mapped_user_id
                    or conversation.surface != AIBuddyConversationSurface.chat
                    or conversation.archived_time is not None
                ):
                    conversation = None
                if conversation is None:
                    default = await ai_buddy_default_model_service.get_enabled_or_none(
                        db=db, kind=AIBuddyModelKind.chat
                    )
                    if default is None:
                        raise errors.RequestError(msg='未配置默认对话模型，无法从通道开对话')
                    conversation_id = uuid4_str()
                    await ai_buddy_conversation_dao.create(
                        db,
                        CreateAIBuddyConversationParam(
                            conversation_id=conversation_id,
                            title=inbound.text[:32] or 'IM 对话',
                            provider_id=default.provider_id,
                            model_id=default.model_id,
                            user_id=mapped_user_id,
                            origin=AIBuddyOrigin.im,
                            channel_id=channel.id,
                        ),
                    )
                    await db.flush()
                    conversation = await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
                    if conversation is None:
                        raise errors.ServerError(msg='创建通道对话失败')
                extra = session_mapping.extra or {}
                history = extra.get('conversation_ids')
                conversation_scope = (
                    [item for item in history if isinstance(item, str)] if isinstance(history, list) else []
                )
                if conversation.conversation_id not in conversation_scope:
                    conversation_scope.append(conversation.conversation_id)
                await ai_buddy_channel_user_dao.update_extra(
                    db,
                    session_mapping.id,
                    {**extra, 'conversation_id': conversation.conversation_id, 'conversation_ids': conversation_scope},
                )
        with _channel_request_context(user_context):
            command_text = inbound.text.lstrip()
            if command_text.startswith('/'):
                parts = command_text[1:].split(maxsplit=1)
                command = parts[0] if parts else ''
                args = parts[1] if len(parts) == 2 else ''
                async with async_db_session.begin() as db:
                    result = await ai_buddy_slash_service.execute(
                        db=db,
                        user_id=mapped_user_id,
                        command=command,
                        origin=AIBuddySlashEntry.im,
                        conversation_id=conversation.conversation_id,
                        args=args,
                        draft=None,
                        conversation_scope=conversation_scope,
                    )
                    slash = result if isinstance(result, dict) else result.model_dump()
                    data = slash.get('data')
                    next_id = data.get('conversation_id') if isinstance(data, dict) else None
                    if slash.get('command') in {'new', 'switch'} and next_id:
                        await db.flush()
                        next_conversation = await ai_buddy_conversation_dao.get_by_conversation_id(db, str(next_id))
                        if next_conversation is None or next_conversation.user_id != mapped_user_id:
                            raise errors.NotFoundError(msg='目标对话不存在')
                        if (
                            next_conversation.surface != AIBuddyConversationSurface.chat
                            or next_conversation.archived_time is not None
                        ):
                            raise errors.RequestError(msg='目标对话不能用于通道聊天')
                        if slash['command'] == 'new':
                            await ai_buddy_conversation_dao.update_channel(db, next_conversation.id, channel.id)
                        await ai_buddy_channel_dao.get_for_update(db, channel.id)
                        latest_mapping = await ai_buddy_channel_user_dao.get_by_external_id(
                            db, channel.id, session_mapping.external_id
                        )
                        if latest_mapping is None:
                            raise errors.NotFoundError(msg='通道会话映射不存在')
                        extra = latest_mapping.extra or {}
                        history = extra.get('conversation_ids')
                        conversation_scope = (
                            [item for item in history if isinstance(item, str)] if isinstance(history, list) else []
                        )
                        if str(next_id) not in conversation_scope:
                            conversation_scope.append(str(next_id))
                        await ai_buddy_channel_user_dao.update_extra(
                            db,
                            latest_mapping.id,
                            {**extra, 'conversation_id': str(next_id), 'conversation_ids': conversation_scope},
                        )
                if slash.get('command') == 'retry':
                    return filter_channel_stream(
                        await attach_event_stream(conversation_id=conversation.conversation_id),
                        show_thinking=channel.show_thinking,
                        show_tool_hints=channel.show_tool_hints,
                    )
                return {'origin': AIBuddyOrigin.im, 'slash': result, 'conversation_id': conversation.conversation_id}
            forwarded = AIBuddyChatForwardedPropsParam(
                provider_id=conversation.provider_id,
                model_id=conversation.model_id,
                agent_mode=conversation.agent_mode or 'work',
            )
            return filter_channel_stream(
                await ai_buddy_chat_service.run_text_prompt(
                    user_id=mapped_user_id,
                    conversation_id=conversation.conversation_id,
                    prompt=inbound.text,
                    forwarded_props=forwarded,
                    origin=AIBuddyOrigin.im,
                ),
                show_thinking=channel.show_thinking,
                show_tool_hints=channel.show_tool_hints,
            )

    @staticmethod
    async def build_approval_card(
        *, db: AsyncSession, pk: int, user_id: int, conversation_id: str, tool_name: str, reason: str
    ) -> dict[str, Any]:
        """
        IM HITL 卡片，审批结果走协议 resume

        :param db: 数据库会话
        :param pk: 通道 ID
        :param user_id: 当前用户 ID
        :param conversation_id: 对话 ID
        :param tool_name: 工具名称
        :param reason: 审批原因
        :return:
        """
        channel = await ai_buddy_channel_dao.get(db, pk)
        conversation = await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
        if (
            channel is None
            or channel.user_id != user_id
            or conversation is None
            or conversation.user_id != user_id
            or conversation.channel_id not in (None, pk)
        ):
            raise errors.NotFoundError(msg='通道或对话不存在')
        return {
            'title': '需要确认',
            'body': reason or f'允许调用 {tool_name}？',
            'payload': {'conversation_id': conversation_id, 'tool_name': tool_name, 'reason': reason},
            'resume': True,
        }

    @staticmethod
    def _filter_discord_inbound(
        *, payload: dict[str, Any], config: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """
        校验 Discord 接收范围与目标机器人提及，并移除正文中的机器人提及

        :param payload: 受认证转发的消息载荷
        :param config: 通道配置
        :return:
        """
        message = payload.get('d') if isinstance(payload.get('d'), dict) else payload
        if payload.get('t') is not None and payload['t'] != 'MESSAGE_CREATE':
            return None, 'unsupported_event'
        author = message.get('author') if isinstance(message.get('author'), dict) else {}
        if author.get('bot') or message.get('webhook_id'):
            return None, 'bot_message'
        channel_id = str(message.get('channel_id') or '').strip()
        author_id = str(author.get('id') or '').strip()
        if not channel_id or not author_id:
            return None, 'missing_message_identity'
        if message.get('guild_id'):
            allowed_channel_ids = config.get('allowed_channel_ids', [])
            if config.get('allow_all_channels', True) is not True and (
                not isinstance(allowed_channel_ids, list) or channel_id not in allowed_channel_ids
            ):
                return None, 'channel_not_allowed'
            bot_id = str(config.get('bot_id') or payload.get('bot_id') or '').strip()
            mentions = message.get('mentions')
            content = message.get('content') or message.get('text') or ''
            if (
                not bot_id
                or not isinstance(mentions, list)
                or not any(isinstance(mention, dict) and str(mention.get('id')) == bot_id for mention in mentions)
                or not isinstance(content, str)
                or not any(mention in content for mention in (f'<@{bot_id}>', f'<@!{bot_id}>'))
            ):
                return None, 'bot_not_mentioned'
            content = content.replace(f'<@{bot_id}>', '').replace(f'<@!{bot_id}>', '').strip()
            if not content:
                return None, 'empty_message'
            message = {**message, 'content': content, 'text': content}
        else:
            allowed_user_ids = config.get('allowed_user_ids', [])
            if not isinstance(allowed_user_ids, list) or author_id not in allowed_user_ids:
                return None, 'user_not_allowed'
        return message, None


ai_buddy_channel_inbound_service: AIBuddyChannelInboundService = AIBuddyChannelInboundService()
