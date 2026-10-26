import asyncio
import contextlib
import json
import secrets

from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store

_TTL = 3600
_MAX_FRAME = 256 * 1024


def _key(bridge_id: str, suffix: str) -> str:
    """
    构建包含作用域的缓存键

    :param bridge_id: 桥接连接 ID
    :param suffix: 缓存键后缀
    :return:
    """
    return f'{shared_chat_run_store.key_prefix}:local-acp:{bridge_id}:{suffix}'


async def create_bridge(*, user_id: int, runner: str, cwd: str) -> dict[str, str]:
    """
    创建用户专属的一次性桌面连接凭证，不接收或执行启动命令

    :param user_id: 当前用户 ID
    :param runner: ACP 执行器名称
    :param cwd: 桌面端工作目录
    :return:
    """
    bridge_id, ticket = uuid4().hex, secrets.token_urlsafe(32)
    record = {'user_id': user_id, 'runner': runner, 'cwd': cwd, 'ticket': ticket}
    await shared_chat_run_store.client.set(_key(bridge_id, 'meta'), json.dumps(record), ex=120)
    return {'bridge_id': bridge_id, 'ticket': ticket}


async def get_bridge(*, bridge_id: str, user_id: int, runner: str) -> dict[str, Any]:
    """
    只允许连接所属用户使用匹配的本地 Agent

    :param bridge_id: 桥接连接 ID
    :param user_id: 当前用户 ID
    :param runner: ACP 执行器名称
    :return:
    """
    client = shared_chat_run_store.client
    raw = await client.get(_key(bridge_id, 'meta'))
    record = json.loads(raw) if raw else {}
    if record.get('user_id') != user_id or record.get('runner') != runner:
        raise errors.RequestError(msg='本地 ACP 连接不存在或不属于当前用户')
    if not await client.exists(_key(bridge_id, 'live')) or await client.exists(_key(bridge_id, 'closed')):
        raise errors.RequestError(msg='本地 ACP Agent 已断开，请在桌面端重新连接')
    return record


async def _push(bridge_id: str, direction: str, data: str) -> None:
    """
    将 ACP 消息写入对应方向的队列

    :param bridge_id: 桥接连接 ID
    :param direction: 消息方向
    :param data: ACP 消息内容
    :return:
    """
    client = shared_chat_run_store.client
    if len(data.encode()) > _MAX_FRAME:
        msg = 'ACP 数据帧过大'
        raise ValueError(msg)
    accepted = await client.eval(
        "if redis.call('llen', KEYS[1]) >= 128 then return 0 end "
        "redis.call('rpush', KEYS[1], ARGV[1]); redis.call('expire', KEYS[1], ARGV[2]); return 1",
        1,
        _key(bridge_id, direction),
        data,
        _TTL,
    )
    if not accepted:
        msg = '本地 ACP 连接积压过多'
        raise ConnectionError(msg)


async def _close_bridge(
    bridge_id: str,
    *,
    metadata: str | bytes | None = None,
    conversation_id: str | None = None,
    claim: str | None = None,
) -> None:
    """
    校验连接归属并清理桥接资源

    :param bridge_id: 桥接连接 ID
    :param metadata: 创建桥接时保存的连接元数据
    :param conversation_id: 当前占用连接的会话 ID
    :param claim: 当前占用连接的凭据
    :return:
    """
    client = shared_chat_run_store.client
    await client.eval(
        "if ARGV[1] ~= '' and redis.call('get', KEYS[1]) ~= ARGV[1] then return 0 end; "
        "local claimed = redis.call('get', KEYS[3]); "
        "if ARGV[2] ~= '' and claimed then "
        'local ok, owner = pcall(cjson.decode, claimed); '
        "if not ok or type(owner) ~= 'table' or owner.conversation_id ~= ARGV[2] then return 0 end end; "
        "if ARGV[3] ~= '' and claimed ~= ARGV[3] then return 0 end; "
        "redis.call('set', KEYS[4], '1', 'EX', ARGV[4]); redis.call('del', KEYS[2]); return 1",
        4,
        *(_key(bridge_id, suffix) for suffix in ('meta', 'live', 'claimed', 'closed')),
        metadata or '',
        conversation_id or '',
        claim or '',
        120,
    )


async def close_owned_bridge(*, bridge_id: str, user_id: int, conversation_id: str | None = None) -> None:
    """
    释放本用户连接，运行清理不能关闭其他对话占用的连接

    :param bridge_id: 桥接连接 ID
    :param user_id: 当前用户 ID
    :param conversation_id: 当前占用连接的会话 ID
    :return:
    """
    raw = await shared_chat_run_store.client.get(_key(bridge_id, 'meta'))
    record = json.loads(raw) if raw else {}
    if record.get('user_id') == user_id:
        await _close_bridge(bridge_id, metadata=raw, conversation_id=conversation_id)


async def serve_bridge(websocket: WebSocket, bridge_id: str) -> None:  # ruff: ignore[complex-structure]
    """
    转发本地 stdio，WebSocket 断开立即撤销连接

    :param websocket: 用于连接桌面端的 WebSocket
    :param bridge_id: 桥接连接 ID
    :return:
    """
    client = shared_chat_run_store.client
    await websocket.accept()
    sender = None
    attached = False
    try:
        async with asyncio.timeout(10):
            auth = await websocket.receive_json()
        raw = await client.get(_key(bridge_id, 'meta'))
        record = json.loads(raw) if raw else {}
        ticket = auth.get('ticket') if isinstance(auth, dict) else None
        if not record or not isinstance(ticket, str) or not secrets.compare_digest(ticket, record.get('ticket', '')):
            await websocket.close(code=1008)
            return
        attached = bool(await client.set(_key(bridge_id, 'attached'), '1', nx=True, ex=_TTL))
        if not attached:
            await websocket.close(code=1008)
            return
        await client.expire(_key(bridge_id, 'meta'), _TTL)
        await client.set(_key(bridge_id, 'live'), '1', ex=30)
        await websocket.send_json({'type': 'ready'})

        async def send() -> None:
            """发送 ACP 协议消息"""
            while await client.exists(_key(bridge_id, 'meta')) and not await client.exists(_key(bridge_id, 'closed')):
                item = await client.blpop(_key(bridge_id, 'stdin'), timeout=1)
                if item:
                    await websocket.send_json({'type': 'stdin', 'data': item[1]})
                else:
                    await websocket.send_json({'type': 'ping'})
            await websocket.send_json({'type': 'close'})
            await websocket.close()

        sender = asyncio.create_task(send())
        while True:
            async with asyncio.timeout(30):
                event = await websocket.receive_json()
            if not isinstance(event, dict):
                msg = '无效的 ACP 数据帧'
                raise TypeError(msg)
            await client.set(_key(bridge_id, 'live'), '1', ex=30)
            if event.get('type') == 'stdout' and isinstance(event.get('data'), str):
                await _push(bridge_id, 'stdout', event['data'])
            elif event.get('type') == 'exit':
                exit_code = event.get('code')
                if isinstance(exit_code, int) and not isinstance(exit_code, bool):
                    await client.set(_key(bridge_id, 'exit_code'), str(exit_code), ex=120)
                break
            elif event.get('type') != 'pong':
                msg = '无效的 ACP 数据帧'
                raise ValueError(msg)
    except (WebSocketDisconnect, TimeoutError, ValueError, TypeError, ConnectionError):
        pass
    finally:
        if sender:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        if attached:
            await _close_bridge(bridge_id)
        with contextlib.suppress(Exception):
            await websocket.close()


class BridgeTransport:
    """ACP SDK 消息传输接口，通过 Redis 连接桌面 stdio"""

    def __init__(self, bridge_id: str, *, claim: str | None = None) -> None:
        """
        初始化 ACP 传输接口

        :param bridge_id: 桥接连接 ID
        :param claim: 当前会话的独占凭据
        :return:
        """
        self.bridge_id = bridge_id
        self._claim = claim
        self._buffer = ''
        self._closed = False
        self._send_lock = asyncio.Lock()

    async def send(self, message: dict[str, Any]) -> None:
        """
        发送 ACP 协议消息

        :param message: ACP 协议消息
        :return:
        """
        if self._closed:
            msg = '本地 ACP 连接已关闭'
            raise ConnectionError(msg)
        data = json.dumps(message, ensure_ascii=True) + '\n'
        if len(data) > 8 * 1024 * 1024:
            msg = 'ACP 请求过大'
            raise ValueError(msg)
        async with self._send_lock:
            for start in range(0, len(data), 65536):
                await _push(self.bridge_id, 'stdin', data[start : start + 65536])

    async def receive(self) -> dict[str, Any] | None:
        """接收 ACP 协议消息或连接终止信号"""
        client = shared_chat_run_store.client
        while not self._closed:
            if '\n' in self._buffer:
                line, self._buffer = self._buffer.split('\n', 1)
                if not line.strip():
                    continue
                message = json.loads(line)
                if not isinstance(message, dict):
                    msg = '无效的 ACP 消息'
                    raise ValueError(msg)
                return message
            item = await client.blpop(_key(self.bridge_id, 'stdout'), timeout=1)
            if item:
                data = item[1]
                self._buffer += data.decode() if isinstance(data, bytes) else data
                if len(self._buffer.encode()) > 8 * 1024 * 1024:
                    msg = 'ACP 消息过大'
                    raise ValueError(msg)
            elif await client.exists(_key(self.bridge_id, 'closed')) or not await client.exists(
                _key(self.bridge_id, 'live'),
            ):
                return None
        return None

    async def close(self) -> None:
        """释放连接及其占用凭据"""
        if self._closed:
            return
        self._closed = True
        self._buffer = ''
        await _close_bridge(self.bridge_id, claim=self._claim)


async def open_bridge_transport(
    *,
    bridge_id: str,
    user_id: int,
    runner: str,
    conversation_id: str | None = None,
) -> BridgeTransport:
    """
    独占桌面 ACP 连接并创建传输接口

    :param bridge_id: 桥接连接 ID
    :param user_id: 当前用户 ID
    :param runner: ACP 执行器名称
    :param conversation_id: 当前会话 ID
    :return:
    """
    await get_bridge(bridge_id=bridge_id, user_id=user_id, runner=runner)
    claim = json.dumps({'conversation_id': conversation_id, 'token': uuid4().hex})
    claimed = await shared_chat_run_store.client.set(_key(bridge_id, 'claimed'), claim, nx=True, ex=_TTL)
    if not claimed:
        raise errors.ConflictError(msg='本地 ACP 连接已被使用，请重新连接')
    return BridgeTransport(bridge_id, claim=claim)


async def get_bridge_exit_code(bridge_id: str) -> int | None:
    """
    读取桌面 ACP 进程退出码

    :param bridge_id: 桥接连接 ID
    :return:
    """
    raw = await shared_chat_run_store.client.get(_key(bridge_id, 'exit_code'))
    return int(raw) if raw is not None else None
