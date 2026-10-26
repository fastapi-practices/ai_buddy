import asyncio
import hashlib

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from octop_gateway.channel import BaseChannel, ChannelCredentialsError
from octop_gateway.manager import ChannelManager
from octop_gateway.media import FileSystemMediaBackend
from octop_gateway.models import InboundMessage, MessageEvent
from starlette.responses import StreamingResponse

from backend.common.log import log
from backend.core.path_conf import BASE_PATH
from backend.database.db import async_db_session, uuid4_str
from backend.database.redis import redis_client
from backend.plugin.ai_buddy.channels.adapters import parse_gateway_message
from backend.plugin.ai_buddy.channels.gateway import GATEWAY_CHANNEL_TYPES, build_gateway_channel
from backend.plugin.ai_buddy.channels.stream import collect_channel_reply
from backend.plugin.ai_buddy.crud.crud_channel import ai_buddy_channel_dao
from backend.plugin.ai_buddy.enums import AIBuddyChannelType
from backend.plugin.ai_buddy.model.channel import AIBuddyChannel
from backend.plugin.ai_buddy.service.channel_inbound_service import ai_buddy_channel_inbound_service

_SYNC_INTERVAL_SECONDS = 5
_LEASE_SECONDS = 60
_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


def _is_control_message(message: InboundMessage) -> bool:
    """禁止合并斜杠指令与同一会话的普通消息

    :param message: 消息内容
    :return:
    """
    return message.text.lstrip().startswith('/')


def _is_stop_message(message: InboundMessage) -> bool:
    """允许停止指令中断正在生成的同一会话

    :param message: 消息内容
    :return:
    """
    return message.text.strip().split(maxsplit=1)[:1] == ['/stop']


@dataclass(slots=True)
class _GatewayWorker:
    channel: AIBuddyChannel
    task: asyncio.Task[None]
    lease_key: str
    owner: str


class AIBuddyGatewayChannelService:
    """管理原生网关通道的启停、账号租约与业务消息处理"""

    async def run_worker(self) -> None:  # ruff: ignore[complex-structure]
        """同步已启用的各平台通道，并在配置变化时重新连接"""
        workers: dict[int, _GatewayWorker] = {}
        try:
            while True:
                try:
                    async with async_db_session() as db:
                        channels = await ai_buddy_channel_dao.get_enabled_by_types(db, tuple(GATEWAY_CHANNEL_TYPES))
                    enabled = {channel.id: channel for channel in channels}
                    for channel_id, worker in list(workers.items()):
                        channel = enabled.get(channel_id)
                        unchanged = channel is not None and (
                            channel.user_id == worker.channel.user_id
                            and channel.type == worker.channel.type
                            and channel.config == worker.channel.config
                            and channel.show_thinking == worker.channel.show_thinking
                            and channel.show_tool_hints == worker.channel.show_tool_hints
                        )
                        if unchanged and not worker.task.done():
                            continue
                        if worker.task.done() and not worker.task.cancelled():
                            exc = worker.task.exception()
                            if exc is not None:
                                log.warning(f'通道 {channel_id} 收发任务退出: {type(exc).__name__}')
                        await self._stop_worker(worker=worker)
                        del workers[channel_id]

                    for channel_id, channel in enabled.items():
                        if channel_id in workers:
                            continue
                        try:
                            native = build_gateway_channel(
                                channel_type=AIBuddyChannelType(channel.type),
                                config=channel.config,
                                channel_id=str(channel.id),
                                tenant_id=str(channel.user_id),
                                processor=self._process_message,
                                show_thinking=channel.show_thinking,
                                show_tool_hints=channel.show_tool_hints,
                            )
                        except ChannelCredentialsError as exc:
                            log.warning(f'通道 {channel_id} 缺少配置字段: {", ".join(exc.missing)}')
                            continue
                        except Exception as exc:
                            log.warning(f'通道 {channel_id} 配置无效: {type(exc).__name__}')
                            continue
                        lease_key = self._channel_lease_key(
                            channel_id=channel.id, channel_type=channel.type, config=channel.config
                        )
                        owner = uuid4_str()
                        if not await redis_client.set(lease_key, owner, nx=True, ex=_LEASE_SECONDS):
                            continue
                        task = asyncio.create_task(
                            self._run_channel(channel=channel, native=native, lease_key=lease_key, owner=owner),
                            name=f'ai-buddy-channel-{channel_id}',
                        )
                        workers[channel_id] = _GatewayWorker(channel, task, lease_key, owner)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning(f'同步网关通道失败: {type(exc).__name__}')
                    await asyncio.gather(
                        *(self._stop_worker(worker=worker) for worker in workers.values()), return_exceptions=True
                    )
                    workers.clear()
                await asyncio.sleep(_SYNC_INTERVAL_SECONDS)
        finally:
            await asyncio.gather(
                *(self._stop_worker(worker=worker) for worker in workers.values()), return_exceptions=True
            )

    @staticmethod
    async def _stop_worker(*, worker: _GatewayWorker) -> None:
        """先停止原生接收和发送任务，再释放本进程的账号租约

        :param worker: 后台任务
        :return:
        """
        worker.task.cancel()
        await asyncio.gather(worker.task, return_exceptions=True)
        await redis_client.eval(_RELEASE_SCRIPT, 1, worker.lease_key, worker.owner)

    @staticmethod
    async def _maintain_lease(*, lease_key: str, owner: str, worker_task: asyncio.Task[Any] | None = None) -> None:
        """
        在连接、生成和资源回收期间续租

        :param lease_key: 账号租约键
        :param owner: 当前进程标识
        :param worker_task: 对应的原生收发任务，清理期间不再取消父任务
        :return:
        """
        while True:
            try:
                renewed = await redis_client.eval(_RENEW_SCRIPT, 1, lease_key, owner, _LEASE_SECONDS)
            except Exception as exc:
                log.warning(f'续期网关通道租约失败: {type(exc).__name__}')
                if worker_task is not None:
                    worker_task.cancel()
                    return
                await asyncio.sleep(_LEASE_SECONDS / 3)
                continue
            if not renewed:
                if worker_task is not None:
                    worker_task.cancel()
                return
            await asyncio.sleep(_LEASE_SECONDS / 3)

    async def _run_channel(self, *, channel: AIBuddyChannel, native: BaseChannel, lease_key: str, owner: str) -> None:
        """
        由 SDK 管理连接、心跳、队列和回复发送，退出时完整关闭资源

        :param channel: 本地通道
        :param native: 待连接的原生通道
        :param lease_key: 账号租约键
        :param owner: 当前进程标识
        :return:
        """
        worker_task = asyncio.current_task()
        if worker_task is None:
            raise RuntimeError('网关通道必须运行在异步任务中')
        lease_task = asyncio.create_task(
            self._maintain_lease(lease_key=lease_key, owner=owner, worker_task=worker_task)
        )
        manager = ChannelManager(
            processor=self._process_message,
            media_backend=FileSystemMediaBackend(BASE_PATH / '.cache' / 'ai_buddy' / 'channels' / str(channel.id)),
            control_message_predicate=_is_control_message,
            interrupt_message_predicate=_is_stop_message,
        )
        try:
            await manager.start()
            await manager.add_channel(native)
            log.info(f'通道 {channel.id}（{channel.type}）已启动原生收发')
            await asyncio.Future()
        finally:
            lease_task.cancel()
            await asyncio.gather(lease_task, return_exceptions=True)
            cleanup_lease_task = asyncio.create_task(self._maintain_lease(lease_key=lease_key, owner=owner))
            try:
                await manager.stop()
                has_live_resources = getattr(native, 'has_live_resources', None)
                while callable(has_live_resources) and has_live_resources():
                    log.warning(f'通道 {channel.id} 仍在回收原生连接资源')
                    try:
                        await native.stop()
                    except Exception as exc:
                        log.warning(f'通道 {channel.id} 资源回收失败: {type(exc).__name__}')
                    if has_live_resources():
                        await asyncio.sleep(1)
                notify_stop = getattr(native, 'notify_stop', None)
                if callable(notify_stop):
                    try:
                        if await redis_client.get(lease_key) == owner:
                            await notify_stop()
                    except Exception as exc:
                        log.warning(f'通道 {channel.id} 下线通知失败: {type(exc).__name__}')
            finally:
                cleanup_lease_task.cancel()
                await asyncio.gather(cleanup_lease_task, return_exceptions=True)

    @staticmethod
    async def _process_message(message: InboundMessage) -> AsyncIterator[MessageEvent]:
        """
        将原生入站交给业务服务，并将完整回复交还原生通道发送

        :param message: 原生 SDK 已校验的消息与回复目标
        :return:
        """
        try:
            if not message.text.strip():
                yield MessageEvent.text('当前通道支持文字和语音转写，请发送文字消息')
                yield MessageEvent.completed()
                return
            inbound = parse_gateway_message(message)
            result = await ai_buddy_channel_inbound_service.handle_inbound(
                pk=int(message.channel_id), user_id=int(message.tenant_id or ''), inbound=inbound
            )
            if isinstance(result, StreamingResponse):
                reply = await collect_channel_reply(result)
            elif result.get('ignored'):
                yield MessageEvent.completed()
                return
            else:
                slash = result.get('slash')
                if hasattr(slash, 'model_dump'):
                    slash = slash.model_dump()
                slash = slash if isinstance(slash, dict) else {}
                data = slash.get('data')
                draft = data.get('draft') if isinstance(data, dict) else None
                reply = str(draft or slash.get('message') or '指令已处理')
            yield MessageEvent.text(reply or '本次没有生成文本回复，请在客户端查看对话结果')
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning(f'通道 {message.channel_id} 处理消息失败: {type(exc).__name__}')
            yield MessageEvent.text('消息处理失败，请稍后重试或在客户端检查默认对话模型配置')
        yield MessageEvent.completed()

    @staticmethod
    def _channel_lease_key(*, channel_id: int, channel_type: str, config: dict[str, Any] | None) -> str:
        """按实际平台账号协调不同配置行和服务进程的接收权

        :param channel_id: 通道 ID
        :param channel_type: 通道类型
        :param config: 配置对象
        :return:
        """
        values = config or {}
        if channel_type == AIBuddyChannelType.wechat:
            accounts = values.get('accounts')
            if isinstance(accounts, list):
                values = next(
                    (item for item in accounts if isinstance(item, dict) and str(item.get('token') or '').strip()),
                    {},
                )
                identity_fields = ('account_id', 'bot_uin', 'token')
            else:
                identity_fields = ('account_id', 'ilink_bot_id', 'bot_uin', 'token', 'bot_token')
            identity = next(
                (str(values[key]).strip() for key in identity_fields if str(values.get(key) or '').strip()),
                str(channel_id),
            )
            account = hashlib.sha256(identity.encode()).hexdigest()
            return f'ai_buddy:wechat:{account}:lease'
        identity = next(
            (
                str(values[key]).strip()
                for key in ('bot_id', 'app_id', 'app_key', 'client_id', 'bot_token', 'token')
                if values.get(key)
            ),
            str(channel_id),
        )
        account = hashlib.sha256(f'{channel_type}:{identity}'.encode()).hexdigest()
        return f'ai_buddy:gateway:{account}:lease'


ai_buddy_gateway_channel_service: AIBuddyGatewayChannelService = AIBuddyGatewayChannelService()
