from typing import Any

from octop_gateway.channel import BaseChannel, ChannelConfig, ChannelCredentialsError, MessageProcessor
from octop_gateway.channels.dingtalk import DingTalkConfig
from octop_gateway.channels.discord import DiscordChannel, DiscordConfig
from octop_gateway.channels.feishu import FeishuConfig
from octop_gateway.channels.qq import QQChannel, QQConfig
from octop_gateway.channels.telegram import TelegramChannel, TelegramConfig
from octop_gateway.channels.wecom import WeComChannel, WeComConfig

from backend.plugin.ai_buddy.channels.gateway_clients import (
    AIBuddyDingTalkChannel,
    AIBuddyFeishuChannel,
    AIBuddyWeixinChannel,
    AIBuddyWeixinConfig,
)
from backend.plugin.ai_buddy.channels.gateway_routing import GatewayRoutingMixin
from backend.plugin.ai_buddy.enums import AIBuddyChannelType


class _FeishuGatewayChannel(GatewayRoutingMixin, AIBuddyFeishuChannel):
    """保留飞书原生协议并兼容资源回收与会话路由"""


class _DingTalkGatewayChannel(GatewayRoutingMixin, AIBuddyDingTalkChannel):
    """保留钉钉原生协议并兼容资源回收与会话路由"""


class _WeComGatewayChannel(GatewayRoutingMixin, WeComChannel):
    """保留企业微信原生协议并隔离会话路由"""


class _QQGatewayChannel(GatewayRoutingMixin, QQChannel):
    """保留 QQ 原生协议并隔离会话路由"""


class _TelegramGatewayChannel(GatewayRoutingMixin, TelegramChannel):
    """保留 Telegram 原生协议并隔离会话路由"""


class _DiscordGatewayChannel(GatewayRoutingMixin, DiscordChannel):
    """保留 Discord 原生协议并隔离会话路由"""


class _WeixinGatewayChannel(GatewayRoutingMixin, AIBuddyWeixinChannel):
    """保留微信原生协议并隔离会话路由"""


_GATEWAY_CHANNELS: dict[AIBuddyChannelType, tuple[type[ChannelConfig], type[BaseChannel]]] = {
    AIBuddyChannelType.wechat: (AIBuddyWeixinConfig, _WeixinGatewayChannel),
    AIBuddyChannelType.feishu: (FeishuConfig, _FeishuGatewayChannel),
    AIBuddyChannelType.dingtalk: (DingTalkConfig, _DingTalkGatewayChannel),
    AIBuddyChannelType.wecom: (WeComConfig, _WeComGatewayChannel),
    AIBuddyChannelType.qq: (QQConfig, _QQGatewayChannel),
    AIBuddyChannelType.telegram: (TelegramConfig, _TelegramGatewayChannel),
    AIBuddyChannelType.discord: (DiscordConfig, _DiscordGatewayChannel),
}
GATEWAY_CHANNEL_TYPES = frozenset(_GATEWAY_CHANNELS)


def build_gateway_channel(
    *,
    channel_type: AIBuddyChannelType | str,
    config: dict[str, Any] | None,
    channel_id: str,
    tenant_id: str,
    processor: MessageProcessor,
    show_thinking: bool = True,
    show_tool_hints: bool = True,
) -> BaseChannel:
    """
    将通道配置转换为原生 SDK 合约并构造待注册通道

    :param channel_type: 通道平台
    :param config: 已保存的平台配置
    :param channel_id: 本地通道 ID
    :param tenant_id: 所属用户 ID
    :param processor: 原生 SDK 消息处理器
    :param show_thinking: 是否展示思考内容
    :param show_tool_hints: 是否展示工具提示
    :return:
    """
    channel_type = AIBuddyChannelType(channel_type)
    channel_spec = _GATEWAY_CHANNELS.get(channel_type)
    if channel_spec is None:
        raise ValueError('该通道不使用网关 SDK')
    config_class, channel_class = channel_spec
    values = dict(config or {})
    if channel_type == AIBuddyChannelType.qq and not values.get('secret'):
        values['secret'] = values.get('app_secret') or values.get('client_secret') or ''
    if channel_type == AIBuddyChannelType.wecom and 'ws_url' not in values:
        values['ws_url'] = values.get('websocket_url') or ''
    if channel_type == AIBuddyChannelType.wechat:
        for canonical, alias in (
            ('token', 'bot_token'),
            ('account_id', 'ilink_bot_id'),
            ('base_url', 'baseurl'),
            ('bound_user_id', 'ilink_user_id'),
        ):
            if not values.get(canonical):
                values[canonical] = values.get(alias) or ''
        values['group_context'] = ChannelConfig.from_dict(values).group_context
    values.update(
        channel_id=channel_id,
        tenant_id=tenant_id,
        show_thinking=show_thinking,
        show_tool_hints=show_tool_hints,
    )
    channel_config = config_class.from_dict(values)
    missing = channel_config.missing_credentials()
    if missing:
        raise ChannelCredentialsError(channel_type.value, missing)
    if channel_type == AIBuddyChannelType.wechat and len(channel_config.accounts) != 1:
        raise ValueError('一个微信通道仅支持一个机器人账号，请分别创建通道')
    return channel_class(processor, config=channel_config, channel_id=channel_id, tenant_id=tenant_id)
