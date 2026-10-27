from dataclasses import replace
from typing import Any

from octop_gateway.channel import BaseChannel, ChannelConfig, MessageProcessor
from octop_gateway.group_context import GroupContextManager
from octop_gateway.models import ChannelSubject, InboundMessage

from backend.plugin.ai_buddy.channels.adapters import parse_gateway_identity

_SESSION_FIELD = '_ai_buddy_session_id'


class _GatewayGroupContextManager(GroupContextManager):
    """按应用群聊或主题键保留短期群上下文"""

    @staticmethod
    def _conversation_id(message: InboundMessage) -> str:
        """
        从网关消息提取对话 ID

        :param message: 网关消息
        :return:
        """
        if _SESSION_FIELD in message.metadata:
            session_id = message.metadata[_SESSION_FIELD]
            return session_id if isinstance(session_id, str) else ''
        return GroupContextManager._conversation_id(message)


class GatewayRoutingMixin(BaseChannel):
    """保留原生发送契约，并隔离应用会话与本次回复的路由快照"""

    def __init__(self, processor: MessageProcessor, *, config: ChannelConfig, **kwargs: Any) -> None:
        """
        初始化网关消息处理器并绑定通道配置

        :param processor: 消息处理器
        :param config: 通道配置
        :param kwargs: 额外关键字参数
        :return:
        """
        super().__init__(processor, config=config, **kwargs)
        context_config = replace(config.group_context, groups=dict(config.group_context.groups))
        self._group_context = _GatewayGroupContextManager(context_config)

    def get_debounce_key(self, message: InboundMessage) -> str:
        """
        让同群成员共用锁，并隔离不同群与主题

        :param message: 消息内容
        :return:
        """
        external_id, session_id = parse_gateway_identity(message)
        return session_id or f'user:{external_id}'

    async def _prepare_inbound(self, raw_payload: object) -> tuple[InboundMessage, ChannelSubject] | None:
        """
        在 SDK 群上下文处理前归一身份，并冻结本次发送目标

        :param raw_payload: 原始载荷
        :return:
        """
        message = self.parse_inbound(raw_payload)
        external_id, session_id = parse_gateway_identity(message)
        if session_id:
            native_group_id = GroupContextManager._conversation_id(message) or session_id.removeprefix('group:')
            policy = self._config.group_context.groups.get(native_group_id)
            if policy is not None:
                self._group_context._config.groups[session_id] = dict(policy)
        message = message.model_copy(
            update={'metadata': {**message.metadata, 'sender_id': external_id, _SESSION_FIELD: session_id}}
        )
        prepared = await super()._prepare_inbound(message)
        if prepared is None:
            return None
        message, subject = prepared
        subject = replace(subject, metadata=dict(message.metadata))
        message.channel_subject = subject
        return message, subject
