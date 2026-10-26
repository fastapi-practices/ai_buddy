import json

from typing import Any

from backend.core.conf import settings
from backend.database.redis import RedisCli, redis_client

_ACTIVE_LEASE_SECONDS = 30
_EVENT_DONE_TTL_SECONDS = 120
_EVENT_STREAM_MAXLEN = 20000
_EVENT_READ_COUNT = 200

_CLAIM_SCRIPT = """
if not redis.call('set', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then
    return 0
end
redis.call('del', KEYS[2])
return 1
"""

_POLL_SCRIPT = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then
    return 0
end
if redis.call('exists', KEYS[2]) == 1 then
    return 1
end
if ARGV[2] == '1' then
    redis.call('expire', KEYS[1], ARGV[3])
end
return 2
"""

_REQUEST_CANCEL_SCRIPT = """
if redis.call('exists', KEYS[1]) == 0 then
    return 0
end
redis.call('set', KEYS[2], '1', 'EX', ARGV[1])
return 1
"""

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) ~= ARGV[1] then
    return 0
end
redis.call('del', KEYS[1], KEYS[2])
return 1
"""


class SharedChatRunStore:
    """基于 Redis 的跨进程聊天任务协调存储"""

    def __init__(self, client: RedisCli = redis_client) -> None:
        """配置 Redis 客户端及聊天任务缓存前缀

        :param client: 客户端
        :return:
        """
        self.client = client
        self.key_prefix = f'{settings.PLUGIN_REDIS_PREFIX}:ai_buddy:chat-run'

    def _key(self, conversation_id: str, suffix: str) -> str:
        """构建包含作用域的缓存键

        :param conversation_id: 对话 ID
        :param suffix: 缓存键后缀
        :return:
        """
        return f'{self.key_prefix}:{conversation_id}:{suffix}'

    async def claim(self, *, conversation_id: str, run_id: str) -> bool:
        """
        获取任务执行租约

        :param conversation_id: 对话 ID
        :param run_id: 运行 ID
        :return:
        """
        result = await self.client.eval(
            _CLAIM_SCRIPT,
            2,
            self._key(conversation_id, 'owner'),
            self._key(conversation_id, 'cancel'),
            run_id,
            _ACTIVE_LEASE_SECONDS,
        )
        if result:
            await self.reset_event_log(conversation_id=conversation_id)
        return bool(result)

    async def is_active(self, *, conversation_id: str) -> bool:
        """
        判断任务租约是否有效

        :param conversation_id: 对话 ID
        :return:
        """
        return bool(await self.client.exists(self._key(conversation_id, 'owner')))

    async def poll(self, *, conversation_id: str, run_id: str, renew: bool) -> int:
        """
        检查租约和取消信号，并按需续期

        :param conversation_id: 对话 ID
        :param run_id: 运行 ID
        :param renew: 是否续期租约
        :return:
        """
        result = int(
            await self.client.eval(
                _POLL_SCRIPT,
                2,
                self._key(conversation_id, 'owner'),
                self._key(conversation_id, 'cancel'),
                run_id,
                '1' if renew else '0',
                _ACTIVE_LEASE_SECONDS,
            )
        )
        if result == 2 and renew:
            await self._expire_event_log(conversation_id=conversation_id, ttl=_ACTIVE_LEASE_SECONDS)
        return result

    async def request_cancel(self, *, conversation_id: str) -> bool:
        """
        设置跨进程取消信号

        :param conversation_id: 对话 ID
        :return:
        """
        result = await self.client.eval(
            _REQUEST_CANCEL_SCRIPT,
            2,
            self._key(conversation_id, 'owner'),
            self._key(conversation_id, 'cancel'),
            _ACTIVE_LEASE_SECONDS,
        )
        return bool(result)

    async def release(self, *, conversation_id: str, run_id: str) -> bool:
        """
        释放当前任务租约和取消信号

        :param conversation_id: 对话 ID
        :param run_id: 运行 ID
        :return:
        """
        result = await self.client.eval(
            _RELEASE_SCRIPT,
            2,
            self._key(conversation_id, 'owner'),
            self._key(conversation_id, 'cancel'),
            run_id,
        )
        return bool(result)

    async def reset_event_log(self, *, conversation_id: str) -> None:
        """
        清空本轮事件日志，供新任务占用

        :param conversation_id: 对话 ID
        :return:
        """
        await self.client.delete(self._key(conversation_id, 'events'), self._key(conversation_id, 'meta'))

    async def set_event_log_meta(
        self,
        *,
        conversation_id: str,
        run_id: str,
        media_type: str,
        headers: dict[str, str],
        closed: bool = False,
        ttl: int | None = None,
    ) -> None:
        """
        写入事件流元信息

        :param conversation_id: 对话 ID
        :param run_id: 运行 ID
        :param media_type: SSE Content-Type
        :param headers: SSE 响应头
        :param closed: 是否已结束
        :param ttl: 过期秒数
        :return:
        """
        payload = json.dumps(
            {
                'run_id': run_id,
                'media_type': media_type,
                'headers': headers,
                'closed': closed,
            },
            ensure_ascii=False,
            separators=(',', ':'),
        )
        await self.client.set(
            self._key(conversation_id, 'meta'),
            payload,
            ex=ttl if ttl is not None else _ACTIVE_LEASE_SECONDS,
        )

    async def get_event_log_meta(self, *, conversation_id: str) -> dict[str, Any] | None:
        """
        读取事件流元信息

        :param conversation_id: 对话 ID
        :return:
        """
        raw = await self.client.get(self._key(conversation_id, 'meta'))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    async def has_event_log(self, *, conversation_id: str) -> bool:
        """
        判断是否存在可重放的事件日志

        :param conversation_id: 对话 ID
        :return:
        """
        return bool(await self.client.exists(self._key(conversation_id, 'events'), self._key(conversation_id, 'meta')))

    async def append_event(self, *, conversation_id: str, payload: str) -> None:
        """
        追加一条已编码 SSE 事件

        :param conversation_id: 对话 ID
        :param payload: 已编码协议事件
        :return:
        """
        key = self._key(conversation_id, 'events')
        await self.client.xadd(
            key,
            {'payload': payload},
            maxlen=_EVENT_STREAM_MAXLEN,
            approximate=True,
        )
        await self._expire_event_log(conversation_id=conversation_id, ttl=_ACTIVE_LEASE_SECONDS)

    async def read_events(
        self,
        *,
        conversation_id: str,
        after_id: str = '0-0',
        count: int = _EVENT_READ_COUNT,
    ) -> list[tuple[str, str]]:
        """
        读取 after_id 之后的事件

        :param conversation_id: 对话 ID
        :param after_id: 上一事件 ID
        :param count: 本批条数
        :return:
        """
        min_id = '-' if after_id in {'0-0', '0'} else f'({after_id}'
        entries = await self.client.xrange(self._key(conversation_id, 'events'), min=min_id, max='+', count=count)
        return _decode_stream_entries(entries)

    async def listen_events(
        self,
        *,
        conversation_id: str,
        after_id: str,
        block_ms: int = 2000,
        count: int = _EVENT_READ_COUNT,
    ) -> list[tuple[str, str]]:
        """
        阻塞等待新事件

        :param conversation_id: 对话 ID
        :param after_id: 上一事件 ID
        :param block_ms: 阻塞毫秒
        :param count: 本批条数
        :return:
        """
        result = await self.client.xread(
            {self._key(conversation_id, 'events'): after_id},
            block=block_ms,
            count=count,
        )
        if not result:
            return []
        return _decode_stream_entries(result[0][1])

    async def close_event_log(self, *, conversation_id: str, run_id: str) -> None:
        """
        标记事件流结束并延长重放窗口

        :param conversation_id: 对话 ID
        :param run_id: 运行 ID
        :return:
        """
        meta = await self.get_event_log_meta(conversation_id=conversation_id)
        media_type = str(meta.get('media_type') or 'text/event-stream') if meta else 'text/event-stream'
        headers = meta.get('headers') if meta and isinstance(meta.get('headers'), dict) else {}
        await self.set_event_log_meta(
            conversation_id=conversation_id,
            run_id=run_id,
            media_type=media_type,
            headers={str(key): str(value) for key, value in headers.items()},
            closed=True,
            ttl=_EVENT_DONE_TTL_SECONDS,
        )
        await self.client.expire(self._key(conversation_id, 'events'), _EVENT_DONE_TTL_SECONDS)

    async def _expire_event_log(self, *, conversation_id: str, ttl: int) -> None:
        """同步续期事件日志及元信息

        :param conversation_id: 对话 ID
        :param ttl: 过期时间
        :return:
        """
        await self.client.expire(self._key(conversation_id, 'events'), ttl)
        await self.client.expire(self._key(conversation_id, 'meta'), ttl)


def _decode_stream_entries(entries: Any) -> list[tuple[str, str]]:
    """解析 Redis 事件日志条目

    :param entries: 事件日志条目
    :return:
    """
    decoded: list[tuple[str, str]] = []
    if not entries:
        return decoded
    for event_id, fields in entries:
        payload = fields.get('payload') if isinstance(fields, dict) else None
        if payload:
            decoded.append((str(event_id), str(payload)))
    return decoded


shared_chat_run_store = SharedChatRunStore()
