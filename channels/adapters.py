import json

from typing import Any

from octop_gateway.models import InboundMessage as GatewayInboundMessage

from backend.common.exception import errors
from backend.plugin.ai_buddy.channels.types import InboundMessage
from backend.plugin.ai_buddy.enums import AIBuddyChannelType


def _text(*candidates: Any) -> str:
    for item in candidates:
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, dict):
            nested = item.get('text') or item.get('content')
            if isinstance(nested, str | list | dict):
                value = _text(nested)
                if value:
                    return value
        if isinstance(item, list):
            parts = [_text(part) for part in item]
            value = '\n'.join(part for part in parts if part)
            if value:
                return value
    return ''


def _id(*candidates: Any) -> str:
    for item in candidates:
        if not isinstance(item, str | int) or isinstance(item, bool):
            continue
        value = str(item).strip()
        if value:
            return value
    return ''


def _session_id(*, chat_id: str, chat_type: str, thread_id: str = '', thread_scope: str = '') -> str | None:
    """
    按群聊或主题标识隔离对话，私聊由发送者隔离

    :param chat_id: 聊天 ID
    :param chat_type: 聊天类型
    :param thread_id: 主题 ID
    :param thread_scope: 主题范围
    :return:
    """
    if thread_id:
        return f'thread:{thread_scope}:{thread_id}' if thread_scope else f'thread:{thread_id}'
    if chat_type in ('group', 'supergroup', 'channel', '2'):
        if not chat_id:
            raise errors.RequestError(msg='通道群消息缺少会话标识')
        return f'group:{chat_id}'
    return None


def parse_gateway_identity(message: GatewayInboundMessage) -> tuple[str, str | None]:
    """
    提取网关 SDK 消息的发送者和应用会话标识

    :param message: SDK 原生消息
    :return:
    """
    subject = message.channel_subject
    metadata = {**(subject.metadata if subject else {}), **message.metadata}
    channel_type = message.channel_type
    chat_type = _id(metadata.get('chat_type'), subject.chat_type if subject else None)
    if metadata.get('is_group') is True or str(metadata.get('conversation_type')) == '2':
        chat_type = 'group'
    if metadata.get('msg_type') == 'channel':
        chat_type = 'group'
    is_group = chat_type in ('group', 'supergroup', 'channel', '2')
    sender_subject = subject.subject_id if subject and (not is_group or channel_type in ('wecom', 'dingtalk')) else None
    external_id = _id(
        metadata.get('sender_id'),
        metadata.get('user_id'),
        metadata.get('from_user_id'),
        metadata.get('to_handle') if not is_group or channel_type in ('wecom', 'dingtalk') else None,
        sender_subject,
    )
    chat_id = _id(
        metadata.get('conversation_id'),
        metadata.get('chat_id'),
        metadata.get('group_openid'),
        metadata.get('group_id'),
        metadata.get('channel_id_native'),
        subject.subject_id if subject and is_group and channel_type not in ('wecom', 'dingtalk') else None,
    )
    thread_id = _id(metadata.get('thread_id'), metadata.get('message_thread_id'))
    if metadata.get('parent_channel_id'):
        thread_id = thread_id or chat_id
    if channel_type == 'telegram' and thread_id and not chat_id:
        raise errors.RequestError(msg='通道主题消息缺少会话标识')
    session_id = _session_id(
        chat_id=chat_id,
        chat_type=chat_type,
        thread_id=thread_id,
        thread_scope=chat_id if channel_type == 'telegram' else '',
    )
    if not external_id or external_id == 'unknown':
        raise errors.RequestError(msg='通道消息缺少外部用户标识')
    return external_id, session_id


def parse_gateway_message(message: GatewayInboundMessage) -> InboundMessage:
    """
    把网关 SDK 消息转换为应用入站契约

    :param message: SDK 原生消息
    :return:
    """
    external_id, session_id = parse_gateway_identity(message)
    text = message.text.strip()
    if not text:
        raise errors.RequestError(msg='通道消息内容为空')
    return InboundMessage(external_id=external_id, text=text, raw=message.model_dump(), session_id=session_id)


def parse_channel_payload(  # ruff: ignore[complex-structure]
    channel_type: AIBuddyChannelType, payload: dict[str, Any]
) -> InboundMessage:
    """
    把各平台入站归一为文本、发送者和群聊或主题标识

    :param channel_type: 通道类型
    :param payload: 原始载荷
    :return:
    """
    event = payload.get('event') if isinstance(payload.get('event'), dict) else {}
    message = payload.get('message') if isinstance(payload.get('message'), dict) else {}
    sender = payload.get('sender') if isinstance(payload.get('sender'), dict) else {}
    session_id = None
    if channel_type == AIBuddyChannelType.feishu:
        sender = event.get('sender') if isinstance(event.get('sender'), dict) else sender
        message = event.get('message') if isinstance(event.get('message'), dict) else message or payload
        sender_id = sender.get('sender_id')
        sender_ids = sender_id if isinstance(sender_id, dict) else {}
        content = message.get('content')
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = None
        text = _text(payload.get('text'), content, event.get('text'))
        if not text and isinstance(content, dict):
            for post in content.values():
                if isinstance(post, dict) and post.get('content'):
                    text = '\n'.join(part for part in (_text(post.get('title')), _text(post.get('content'))) if part)
                    break
        external_id = _id(
            payload.get('external_id'),
            sender_ids.get('open_id'),
            sender_ids.get('user_id'),
            sender_ids.get('union_id'),
            sender_id,
            payload.get('sender_id'),
        )
        session_id = _session_id(
            chat_id=_id(message.get('chat_id')),
            chat_type=_id(message.get('chat_type')),
            thread_id=_id(message.get('thread_id')),
        )
    elif channel_type == AIBuddyChannelType.dingtalk:
        text = _text(payload.get('text'), payload.get('content'))
        external_id = _id(
            payload.get('external_id'), payload.get('senderStaffId'), payload.get('senderId'), payload.get('sender_id')
        )
        if not text and isinstance(payload.get('content'), dict):
            text = _text(payload['content'].get('richText'))
        session_id = _session_id(
            chat_id=_id(payload.get('conversationId'), payload.get('conversation_id')),
            chat_type=_id(payload.get('conversationType'), payload.get('conversation_type')),
        )
    elif channel_type == AIBuddyChannelType.wechat:
        items = payload.get('item_list')
        parts = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get('type') == 1:
                parts.append(_text(item.get('text_item')))
            elif item.get('type') == 3:
                parts.append(_text(item.get('voice_item')))
        text = _text(payload.get('Content'), payload.get('text'), payload.get('content'), '\n'.join(parts))
        external_id = _id(
            payload.get('external_id'), payload.get('from_user_id'), payload.get('FromUserName'), payload.get('from')
        )
    elif channel_type == AIBuddyChannelType.wecom:
        body = payload.get('body') if isinstance(payload.get('body'), dict) else payload
        from_user = body.get('from') if isinstance(body.get('from'), dict) else {}
        mixed = body.get('mixed') if isinstance(body.get('mixed'), dict) else {}
        text = _text(body.get('Content'), body.get('text'), body.get('content'), mixed.get('msg_item'))
        external_id = _id(
            payload.get('external_id'),
            body.get('external_id'),
            from_user.get('userid'),
            from_user.get('user_id'),
            body.get('FromUserName'),
            body.get('from'),
        )
        session_id = _session_id(
            chat_id=_id(body.get('chatid'), body.get('chat_id')),
            chat_type=_id(body.get('chattype'), body.get('chat_type')),
        )
    elif channel_type == AIBuddyChannelType.telegram:
        chat = message.get('chat') if isinstance(message.get('chat'), dict) else payload.get('chat') or {}
        chat = chat if isinstance(chat, dict) else {}
        from_user = message.get('from') if isinstance(message.get('from'), dict) else payload.get('from') or {}
        text = _text(payload.get('text'), message.get('text'), message.get('caption'), payload.get('content'))
        external_id = _id(
            payload.get('external_id'),
            from_user.get('id') if isinstance(from_user, dict) else from_user,
            payload.get('user_id'),
        )
        chat_id = _id(chat.get('id'), payload.get('chat_id'))
        thread_id = _id(message.get('message_thread_id'), payload.get('message_thread_id'))
        if thread_id and not chat_id:
            raise errors.RequestError(msg='通道主题消息缺少会话标识')
        session_id = _session_id(
            chat_id=chat_id,
            chat_type='group' if payload.get('is_group') is True else _id(chat.get('type')),
            thread_id=thread_id,
            thread_scope=chat_id,
        )
    elif channel_type == AIBuddyChannelType.discord:
        data = payload.get('d') if isinstance(payload.get('d'), dict) else payload
        author = data.get('author') if isinstance(data.get('author'), dict) else {}
        text = _text(data.get('content'), data.get('text'))
        external_id = _id(payload.get('external_id'), data.get('external_id'), author.get('id'), data.get('user_id'))
        chat_id = _id(data.get('channel_id'))
        session_id = _session_id(
            chat_id=chat_id,
            chat_type='group' if data.get('guild_id') else _id(data.get('chat_type')),
            thread_id=chat_id if data.get('parent_channel_id') else _id(data.get('thread_id')),
        )
    elif channel_type == AIBuddyChannelType.qq:
        data = payload.get('d') if isinstance(payload.get('d'), dict) else payload
        author = data.get('author') if isinstance(data.get('author'), dict) else {}
        sender = data.get('sender') if isinstance(data.get('sender'), dict) else {}
        text = _text(data.get('raw_message'), data.get('message'), data.get('content'), data.get('text'))
        if not text and isinstance(data.get('message'), list):
            text = '\n'.join(
                _text(item.get('data'))
                for item in data['message']
                if isinstance(item, dict) and item.get('type') == 'text'
            ).strip()
        external_id = _id(
            payload.get('external_id'),
            data.get('external_id'),
            author.get('member_openid'),
            author.get('user_openid'),
            author.get('id'),
            data.get('member_openid'),
            data.get('user_openid'),
            data.get('user_id'),
            sender.get('user_id'),
        )
        event_type = _id(payload.get('t'), payload.get('event_type'))
        is_group = bool(
            data.get('group_openid')
            or data.get('group_id')
            or event_type in ('GROUP_AT_MESSAGE_CREATE', 'GROUP_MESSAGE_CREATE', 'AT_MESSAGE_CREATE', 'MESSAGE_CREATE')
            or (data.get('guild_id') and event_type not in ('DIRECT_MESSAGE_CREATE', 'C2C_MESSAGE_CREATE'))
        )
        session_id = _session_id(
            chat_id=_id(data.get('group_openid'), data.get('group_id'), data.get('channel_id')),
            chat_type='group' if is_group else _id(data.get('message_type')),
            thread_id=_id(data.get('thread_id')),
        )
    else:
        text = _text(payload.get('text'), payload.get('content'))
        external_id = _id(payload.get('external_id'), payload.get('user_id'))
    if not external_id:
        raise errors.RequestError(msg='通道消息缺少外部用户标识')
    if not text:
        raise errors.RequestError(msg='通道消息内容为空')
    return InboundMessage(
        external_id=external_id, text=text, raw=payload, session_id=_id(payload.get('session_id')) or session_id
    )
