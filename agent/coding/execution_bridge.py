from __future__ import annotations

import asyncio
import contextlib
import json
import secrets

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import WebSocketDisconnect

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store
from backend.plugin.ai_buddy.enums import AIBuddyExecutionBackend, AIBuddyExecutionMethod
from backend.plugin.ai_buddy.schema.execution import AIBuddyExecutionResponse

if TYPE_CHECKING:
    from fastapi import WebSocket

    from backend.plugin.ai_buddy.enums import AIBuddyPermissionMode
    from backend.plugin.ai_buddy.schema.execution import (
        AIBuddyDesktopExecutionBackend,
        CreateAIBuddyExecutionBridgeParam,
    )

_TTL = 3600
_TICKET_TTL = 120
_LIVE_TTL = 30
_MAX_QUEUE = 128


def _key(bridge_id: str, suffix: str) -> str:
    """构建包含作用域的缓存键

    :param bridge_id: 桥接连接 ID
    :param suffix: 缓存键后缀
    :return:
    """
    return f'{shared_chat_run_store.key_prefix}:execution:{bridge_id}:{suffix}'


async def create_bridge(*, user_id: int, obj: CreateAIBuddyExecutionBridgeParam) -> dict[str, str]:
    """创建用户专属的一次性桌面执行凭证

    :param user_id: 用户 ID
    :param obj: 创建桥接参数
    :return:
    """
    bridge_id, ticket = uuid4().hex, secrets.token_urlsafe(32)
    record = {
        'user_id': user_id,
        **obj.model_dump(),
        'ticket': ticket,
        'limits': {
            'max_file_bytes': settings.AI_BUDDY_AGENT_MAX_FILE_BYTES,
            'bash_timeout_seconds': settings.AI_BUDDY_AGENT_BASH_TIMEOUT_SECONDS,
        },
    }
    await shared_chat_run_store.client.set(_key(bridge_id, 'meta'), json.dumps(record), ex=_TICKET_TTL)
    return {'bridge_id': bridge_id, 'ticket': ticket}


async def get_bridge(
    *, bridge_id: str, user_id: int, backend: AIBuddyDesktopExecutionBackend, permission_mode: AIBuddyPermissionMode
) -> dict[str, Any]:
    """只允许所属用户使用匹配后端和权限的在线连接

    :param bridge_id: 桥接连接 ID
    :param user_id: 用户 ID
    :param backend: 执行后端
    :param permission_mode: 权限模式
    :return:
    """
    client = shared_chat_run_store.client
    raw = await client.get(_key(bridge_id, 'meta'))
    record = json.loads(raw) if raw else {}
    if backend != AIBuddyExecutionBackend.local or record.get('user_id') != user_id or record.get('backend') != backend:
        raise errors.RequestError(msg='桌面执行连接不存在、不属于当前用户或执行后端不匹配')
    if record.get('permission_mode') != permission_mode:
        raise errors.RequestError(msg='桌面执行连接权限不匹配，请重新连接')
    if not await client.exists(_key(bridge_id, 'live')) or await client.exists(_key(bridge_id, 'closed')):
        raise errors.RequestError(msg='桌面执行连接已断开，请在桌面端重新连接')
    return record


async def _close_bridge(
    bridge_id: str, *, metadata: str | bytes | None = None, conversation_id: str | None = None, claim: str | None = None
) -> None:
    """校验连接归属并清理桥接资源

    :param bridge_id: 桥接连接 ID
    :param metadata: 连接元数据
    :param conversation_id: 对话 ID
    :param claim: 独占凭据
    :return:
    """
    client = shared_chat_run_store.client
    await client.eval(
        "if ARGV[1] ~= '' and redis.call('get', KEYS[1]) ~= ARGV[1] then return 0 end; "
        "local claimed = redis.call('get', KEYS[4]); "
        "if ARGV[2] ~= '' and claimed and cjson.decode(claimed).conversation_id ~= ARGV[2] then return 0 end; "
        "if ARGV[3] ~= '' and claimed ~= ARGV[3] then return 0 end; "
        "redis.call('set', KEYS[5], '1', 'EX', ARGV[4]); "
        "redis.call('del', KEYS[1], KEYS[2], KEYS[3], KEYS[4]); return 1",
        5,
        *(_key(bridge_id, suffix) for suffix in ('meta', 'live', 'requests', 'claimed', 'closed')),
        metadata or '',
        conversation_id or '',
        claim or '',
        _TICKET_TTL,
    )


async def close_owned_bridge(*, bridge_id: str, user_id: int, conversation_id: str | None = None) -> None:
    """释放本用户连接，运行清理不能关闭其他对话占用的连接

    :param bridge_id: 桥接连接 ID
    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :return:
    """
    raw = await shared_chat_run_store.client.get(_key(bridge_id, 'meta'))
    record = json.loads(raw) if raw else {}
    if record.get('user_id') == user_id:
        await _close_bridge(bridge_id, metadata=raw, conversation_id=conversation_id)


async def _receive_frame(websocket: WebSocket, *, timeout: int) -> dict[str, Any]:
    """在超时内接收并校验桌面连接消息

    :param websocket: WebSocket 连接
    :param timeout: 超时时间
    :return:
    """
    async with asyncio.timeout(timeout):
        data = await websocket.receive_text()
    frame = json.loads(data)
    if not isinstance(frame, dict):
        raise TypeError('无效的桌面执行数据帧')
    return frame


async def _send_frames(websocket: WebSocket, bridge_id: str) -> None:
    """将服务端队列消息转发到桌面连接

    :param websocket: WebSocket 连接
    :param bridge_id: 桥接连接 ID
    :return:
    """
    client = shared_chat_run_store.client
    while await client.exists(_key(bridge_id, 'meta')) and not await client.exists(_key(bridge_id, 'closed')):
        item = await client.blpop(_key(bridge_id, 'requests'), timeout=1)
        frame = json.loads(item[1]) if item else {'type': 'ping'}
        accepted = await client.eval(
            "if redis.call('exists', KEYS[1]) == 0 or redis.call('exists', KEYS[2]) == 0 "
            "or redis.call('exists', KEYS[3]) == 1 then return -1 end; "
            "if ARGV[1] ~= '' then local pending = redis.call('get', KEYS[5]); "
            "if not pending or pending ~= redis.call('get', KEYS[4]) then return 0 end end; return 1",
            5,
            *(_key(bridge_id, suffix) for suffix in ('meta', 'live', 'closed', 'claimed')),
            _key(bridge_id, f'pending:{frame.get("id", "")}'),
            frame.get('id', ''),
        )
        if accepted == -1:
            break
        if accepted:
            await websocket.send_json(frame)
    await websocket.send_json({'type': 'close'})


async def _receive_frames(websocket: WebSocket, bridge_id: str) -> None:
    """接收桌面响应并写入等待队列

    :param websocket: WebSocket 连接
    :param bridge_id: 桥接连接 ID
    :return:
    """
    client = shared_chat_run_store.client
    while True:
        event = await _receive_frame(websocket, timeout=_LIVE_TTL)
        if event == {'type': 'pong'}:
            await client.set(_key(bridge_id, 'live'), '1', ex=_LIVE_TTL)
            continue
        response = AIBuddyExecutionResponse.model_validate(event)
        await client.set(_key(bridge_id, 'live'), '1', ex=_LIVE_TTL)
        await client.eval(
            "local claim = redis.call('get', KEYS[1]); "
            "if not claim or claim ~= redis.call('get', KEYS[2]) or redis.call('exists', KEYS[4]) == 1 "
            'then return 0 end; '
            "redis.call('del', KEYS[1]); redis.call('rpush', KEYS[3], ARGV[1]); "
            "redis.call('expire', KEYS[3], 60); return 1",
            4,
            _key(bridge_id, f'pending:{response.id}'),
            _key(bridge_id, 'claimed'),
            _key(bridge_id, f'response:{response.id}'),
            _key(bridge_id, 'closed'),
            response.model_dump_json(),
        )


async def serve_bridge(websocket: WebSocket, bridge_id: str) -> None:
    """认证后只转发执行 RPC，断线立即撤销会话

    :param websocket: WebSocket 连接
    :param bridge_id: 桥接连接 ID
    :return:
    """
    client = shared_chat_run_store.client
    tasks: list[asyncio.Task[None]] = []
    attached = False
    await websocket.accept()
    try:
        auth = await _receive_frame(websocket, timeout=10)
        raw = await client.get(_key(bridge_id, 'meta'))
        record = json.loads(raw) if raw else {}
        ticket = auth.get('ticket')
        if (
            record.get('backend') != AIBuddyExecutionBackend.local
            or set(auth) != {'ticket'}
            or not isinstance(ticket, str)
            or not ticket
            or not secrets.compare_digest(ticket, record.get('ticket', ''))
        ):
            await websocket.close(code=1008)
            return
        record.pop('ticket', None)
        attached = bool(
            await client.eval(
                "if redis.call('get', KEYS[1]) ~= ARGV[1] or redis.call('exists', KEYS[2]) == 1 "
                "or redis.call('exists', KEYS[3]) == 1 then return 0 end; "
                "redis.call('set', KEYS[1], ARGV[2], 'EX', ARGV[3]); "
                "redis.call('set', KEYS[2], '1', 'EX', ARGV[3]); "
                "redis.call('set', KEYS[4], '1', 'EX', ARGV[4]); return 1",
                4,
                _key(bridge_id, 'meta'),
                _key(bridge_id, 'attached'),
                _key(bridge_id, 'closed'),
                _key(bridge_id, 'live'),
                raw,
                json.dumps(record),
                _TTL,
                _LIVE_TTL,
            )
        )
        if not attached:
            await websocket.close(code=1008)
            return
        await websocket.send_json({
            'type': 'ready',
            'backend': record['backend'],
            'cwd': record['cwd'],
            'permission_mode': record['permission_mode'],
            'limits': record['limits'],
            'capabilities': record['capabilities'],
        })
        tasks = [
            asyncio.create_task(_send_frames(websocket, bridge_id)),
            asyncio.create_task(_receive_frames(websocket, bridge_id)),
        ]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except (WebSocketDisconnect, TimeoutError, ValueError, TypeError, ConnectionError):
        with contextlib.suppress(Exception):
            await websocket.close(code=1008)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if attached:
            await _close_bridge(bridge_id)
        with contextlib.suppress(Exception):
            await websocket.close()


class ExecutionBridge:
    """绑定用户和编码会话的桌面 RPC 客户端"""

    def __init__(self, *, bridge_id: str, record: dict[str, Any], claim: str) -> None:
        """保存桌面连接状态与独占凭据

        :param bridge_id: 桥接连接 ID
        :param record: 桥接连接记录
        :param claim: 独占凭据
        :return:
        """
        self.bridge_id = bridge_id
        self.record = record
        self._claim = claim
        self._closed = False
        self._lock = asyncio.Lock()

    async def check_connection(self) -> None:
        """校验当前桌面连接仍然可用"""
        if self._closed:
            raise errors.RequestError(msg='桌面执行连接已关闭')
        await get_bridge(
            bridge_id=self.bridge_id,
            user_id=self.record['user_id'],
            backend=self.record['backend'],
            permission_mode=self.record['permission_mode'],
        )
        claimed = await shared_chat_run_store.client.get(_key(self.bridge_id, 'claimed'))
        if claimed not in (self._claim, self._claim.encode()):
            raise errors.RequestError(msg='桌面执行连接不属于当前编码会话')

    async def request(
        self, method: AIBuddyExecutionMethod, params: dict[str, Any], *, timeout: float | None = None
    ) -> Any:
        """发送桌面执行请求并等待关联响应

        :param method: 方法名称
        :param params: 方法参数
        :param timeout: 超时时间
        :return:
        """
        if method not in AIBuddyExecutionMethod.get_member_values():
            raise ValueError('不支持的桌面执行方法')
        capability = {
            'run_tests': ('run_tests_v1', '桌面端未协商测试报告能力'),
            'run_command': ('command_v1', '桌面端未协商受控命令能力，请更新桌面端'),
            'write_input_file': ('input_files_v1', '桌面端未协商附件写入能力，请更新桌面端'),
            'git_status': ('workspace_git_v1', '桌面端未协商工作区 Git 查询能力'),
            'git_diff': ('workspace_git_v1', '桌面端未协商工作区 Git 查询能力'),
        }.get(method)
        if capability is not None and capability[0] not in self.record.get('capabilities', []):
            raise errors.RequestError(msg=capability[1])
        request_id = uuid4().hex
        wait_seconds = timeout if timeout is not None else max(30, self.record['limits']['bash_timeout_seconds'] + 5)
        client = shared_chat_run_store.client
        async with self._lock:
            try:
                async with asyncio.timeout(wait_seconds):
                    await self.check_connection()
                    data = json.dumps({'id': request_id, 'method': method, 'params': params}, ensure_ascii=False)
                    accepted = await client.eval(
                        "if redis.call('exists', KEYS[2]) == 0 or redis.call('exists', KEYS[3]) == 1 "
                        "or redis.call('get', KEYS[4]) ~= ARGV[1] then return -1 end; "
                        "if redis.call('llen', KEYS[1]) >= tonumber(ARGV[5]) then return 0 end; "
                        "redis.call('set', KEYS[5], ARGV[1], 'EX', ARGV[4]); "
                        "redis.call('rpush', KEYS[1], ARGV[2]); redis.call('expire', KEYS[1], ARGV[3]); return 1",
                        5,
                        _key(self.bridge_id, 'requests'),
                        _key(self.bridge_id, 'live'),
                        _key(self.bridge_id, 'closed'),
                        _key(self.bridge_id, 'claimed'),
                        _key(self.bridge_id, f'pending:{request_id}'),
                        self._claim,
                        data,
                        _TTL,
                        int(wait_seconds) + 5,
                        _MAX_QUEUE,
                    )
                    if accepted != 1:
                        raise errors.RequestError(msg='桌面执行连接已断开或请求积压过多')
                    while True:
                        item = await client.blpop(_key(self.bridge_id, f'response:{request_id}'), timeout=1)
                        if item:
                            response = AIBuddyExecutionResponse.model_validate_json(item[1])
                            if response.error is not None:
                                raise errors.RequestError(msg=f'{response.error.code}: {response.error.message}')
                            return response.result
                        await self.check_connection()
            except TimeoutError as exc:
                await self.close()
                raise errors.RequestError(msg='桌面执行请求超时，连接已关闭，请重新连接') from exc
            except asyncio.CancelledError:
                await self.close()
                raise
            finally:
                await client.delete(
                    _key(self.bridge_id, f'pending:{request_id}'), _key(self.bridge_id, f'response:{request_id}')
                )

    async def close(self) -> None:
        """释放连接及其占用凭据"""
        if self._closed:
            return
        self._closed = True
        await _close_bridge(self.bridge_id, claim=self._claim)


async def open_bridge(
    *,
    bridge_id: str,
    user_id: int,
    backend: AIBuddyDesktopExecutionBackend,
    permission_mode: AIBuddyPermissionMode,
    conversation_id: str,
) -> ExecutionBridge:
    """校验并独占当前对话的桌面执行连接

    :param bridge_id: 桥接连接 ID
    :param user_id: 用户 ID
    :param backend: 执行后端
    :param permission_mode: 权限模式
    :param conversation_id: 对话 ID
    :return:
    """
    record = await get_bridge(bridge_id=bridge_id, user_id=user_id, backend=backend, permission_mode=permission_mode)
    claim = json.dumps({'conversation_id': conversation_id, 'session_id': uuid4().hex})
    accepted = await shared_chat_run_store.client.eval(
        "if redis.call('get', KEYS[1]) ~= ARGV[1] or redis.call('exists', KEYS[2]) == 0 "
        "or redis.call('exists', KEYS[3]) == 1 then return -1 end; "
        "if redis.call('exists', KEYS[4]) == 1 then return 0 end; "
        "redis.call('set', KEYS[4], ARGV[2], 'EX', ARGV[3]); return 1",
        4,
        *(_key(bridge_id, suffix) for suffix in ('meta', 'live', 'closed', 'claimed')),
        json.dumps(record),
        claim,
        _TTL,
    )
    if accepted == -1:
        raise errors.RequestError(msg='桌面执行连接已断开或连接配置已变更，请重新连接')
    if not accepted:
        raise errors.ConflictError(msg='桌面执行连接已被编码会话使用，请重新连接')
    return ExecutionBridge(bridge_id=bridge_id, record=record, claim=claim)
