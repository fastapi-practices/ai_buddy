import asyncio
import json

from dataclasses import dataclass
from types import FunctionType, MethodType, SimpleNamespace
from typing import Any
from urllib.parse import quote_plus

import requests
import websockets

from octop_gateway.channels.dingtalk import DingTalkChannel
from octop_gateway.channels.feishu import FeishuChannel
from octop_gateway.channels.weixin import WeixinChannel, WeixinConfig
from octop_gateway.channels.weixin.api import _CHANNEL_VERSION
from octop_gateway.channels.weixin.types import WeixinAPIError, WeixinMessage

from backend.common.log import log

_REQUEST_TIMEOUT = (5.0, 10.0)
_THREAD_STOP_TIMEOUT = 30.0
_SOCKET_CLOSE_TIMEOUT = 5.0
_WEIXIN_NOTIFICATION_TIMEOUT = 10.0


@dataclass
class AIBuddyWeixinConfig(WeixinConfig):
    """保留原生微信配置并限制扫码绑定用户"""

    bound_user_id: str = ''


class AIBuddyWeixinChannel(WeixinChannel):
    """保留微信原生协议并补充上线通知与绑定用户边界"""

    async def _notify_lifecycle(self, *, endpoint: str) -> None:
        """
        通过 SDK 传输客户端通知微信上线或下线

        :param endpoint: 微信生命周期通知路径
        :return:
        """
        async with asyncio.timeout(_WEIXIN_NOTIFICATION_TIMEOUT):
            for account in self._config.accounts:
                api = await self._api(account)
                await api._post_json(endpoint, {'base_info': {'channel_version': _CHANNEL_VERSION}})

    async def start(self) -> None:
        """启动微信网关并同步上线通知"""
        try:
            try:
                await self._notify_lifecycle(endpoint='ilink/bot/msg/notifystart')
            except WeixinAPIError as exc:
                if exc.ret not in (-14, -2) and exc.errcode not in (-14, -2):
                    raise
                log.warning('微信登录状态已失效，请重新扫码')
            await super().start()
        except Exception:
            raise RuntimeError('微信上线失败，请检查通道凭证或重新扫码') from None

    async def notify_stop(self) -> None:
        """仅由仍持有账号租约的调用方在接收资源关闭后通知下线"""
        try:
            await self._notify_lifecycle(endpoint='ilink/bot/msg/notifystop')
        except Exception:
            raise RuntimeError('微信下线通知失败') from None
        finally:
            await self._close_http()

    def _dispatch_message(self, account_id: str, msg: WeixinMessage) -> None:
        """
        按绑定用户过滤并分发微信消息

        :param account_id: 网关账号 ID
        :param msg: 微信消息
        :return:
        """
        bound_user = str(getattr(self._config, 'bound_user_id', '') or '').strip()
        if bound_user and msg.from_user_id != bound_user:
            return
        if not msg.from_user_id or not msg.context_token:
            return
        super()._dispatch_message(account_id, msg)


def _post_with_timeout(url: str, **kwargs: Any) -> requests.Response:
    """
    在 SDK 同步 HTTP 边界补充连接与读取超时

    :param url: 请求地址
    :param kwargs: 额外关键字参数
    :return:
    """
    kwargs.setdefault('timeout', _REQUEST_TIMEOUT)
    return requests.post(url, **kwargs)


def _bind_sdk_method(method: MethodType, *, globals_override: dict[str, Any]) -> MethodType:
    """
    保留 SDK 函数代码，在实例上隔离其传输依赖与事件循环

    :param method: 方法名称
    :param globals_override: 全局变量覆盖项
    :return:
    """
    source = method.__func__
    function = FunctionType(
        source.__code__,
        source.__globals__ | globals_override,
        source.__name__,
        source.__defaults__,
        source.__closure__,
    )
    function.__kwdefaults__ = source.__kwdefaults__
    function.__annotations__ = source.__annotations__
    return MethodType(function, method.__self__)


async def _run_dingtalk_stream(*, client: Any) -> None:
    """
    保留 SDK 回调与心跳协议，异步调度阻塞的连接申请并回收其子任务

    :param client: 客户端
    :return:
    """
    client.pre_start()
    children: set[asyncio.Task[Any]] = set()
    while True:
        try:
            connection_task = asyncio.create_task(asyncio.to_thread(client.open_connection))
            try:
                connection = await asyncio.shield(connection_task)
            except asyncio.CancelledError:
                try:
                    await connection_task
                except Exception as exc:
                    log.warning(f'取消钉钉连接申请失败: {type(exc).__name__}')
                raise
            if not connection:
                await asyncio.sleep(10)
                continue
            uri = f'{connection["endpoint"]}?ticket={quote_plus(connection["ticket"])}'
            async with websockets.connect(
                uri, open_timeout=_REQUEST_TIMEOUT[0], close_timeout=_SOCKET_CLOSE_TIMEOUT
            ) as websocket:
                client.websocket = websocket
                children.add(asyncio.create_task(client.keepalive(websocket)))
                async for raw in websocket:
                    task = asyncio.create_task(client.background_task(json.loads(raw)))
                    children.add(task)
                    task.add_done_callback(children.discard)
        except Exception as exc:
            log.warning(f'钉钉 Stream 连接失败: {type(exc).__name__}')
            await asyncio.sleep(3)
        finally:
            for task in children:
                task.cancel()
            if children:
                await asyncio.gather(*children, return_exceptions=True)
            children.clear()
            client.websocket = None


class AIBuddyDingTalkChannel(DingTalkChannel):
    """兼容 SDK 阻塞连接申请与取消行为的钉钉原生通道"""

    async def _start_stream_client(self) -> None:
        """启动钉钉流客户端并接管阻塞连接"""
        await super()._start_stream_client()
        initial_task = self._stream_task
        if initial_task is not None:
            initial_task.cancel()
            await asyncio.gather(initial_task, return_exceptions=True)
        client = self._stream_client
        client.open_connection = _bind_sdk_method(
            client.open_connection, globals_override={'requests': SimpleNamespace(post=_post_with_timeout)}
        )
        self._stream_task = asyncio.create_task(
            _run_dingtalk_stream(client=client), name=f'ai-buddy-dingtalk-stream-{self.channel_id}'
        )

    async def _stop_stream_client(self) -> None:
        """停止钉钉流任务并清理会话状态"""
        task = self._stream_task
        if task is not None:
            if not task.cancelling():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._stream_task = None
        self._stream_client = None
        self._stream_session_id = None

    def has_live_resources(self) -> bool:
        """判断连接申请、WebSocket 或消息分发任务是否仍未退出"""
        return self._stream_task is not None and not self._stream_task.done()


class AIBuddyFeishuChannel(FeishuChannel):
    """隔离各账号的 SDK 线程事件循环，并完整回收飞书连接资源"""

    async def _start_ws_client(self) -> None:
        """重置飞书 WebSocket 停止状态并启动客户端"""
        self._ws_stop_requested = False
        self._ws_cleanup_failed = False
        await super()._start_ws_client()

    def _run_ws_thread(self) -> None:  # ruff: ignore[complex-structure]
        """在独立事件循环中运行飞书 WebSocket SDK"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._ws_loop = loop
        client = self._ws_client
        run_until_complete = loop.run_until_complete

        def run_sdk(awaitable: Any) -> Any:
            # SDK 在两次运行循环之间可能开始新任务，停机后禁止再次进入循环
            """
            在网关事件循环中执行 SDK 异步调用

            :param awaitable: SDK 异步调用
            :return:
            """
            if self._ws_stop_requested:
                awaitable.close()
                raise asyncio.CancelledError
            return run_until_complete(awaitable)

        try:
            if client is None:
                return
            self._ws_cache_task = client._cache._cron
            self._ws_cache_task.get_loop().call_soon_threadsafe(self._ws_cache_task.cancel)
            client._cache._cron = loop.create_task(client._cache._start_clear_cron())
            overrides = {'loop': loop, 'requests': SimpleNamespace(post=_post_with_timeout)}
            for name, function in vars(type(client)).items():
                if isinstance(function, FunctionType) and {'loop', 'requests'}.intersection(function.__code__.co_names):
                    setattr(client, name, _bind_sdk_method(getattr(client, name), globals_override=overrides))
            if self._ws_stop_requested:
                return
            loop.run_until_complete = run_sdk
            client.start()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning(f'飞书 WebSocket 线程退出: {type(exc).__name__}')
        finally:
            loop.run_until_complete = run_until_complete
            if client is not None:
                client._auto_reconnect = False
            connection = client._conn if client is not None else None
            tasks = asyncio.all_tasks(loop)
            for task in tasks:
                task.cancel()
            if tasks:
                loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            if client is not None:
                try:
                    loop.run_until_complete(asyncio.wait_for(client._disconnect(), timeout=_SOCKET_CLOSE_TIMEOUT))
                    if connection is not None:
                        loop.run_until_complete(asyncio.wait_for(connection.close(), timeout=_SOCKET_CLOSE_TIMEOUT))
                except Exception as exc:
                    log.warning(f'飞书 WebSocket 关闭失败: {type(exc).__name__}')
                    transport = getattr(connection, 'transport', None)
                    if transport is not None:
                        try:
                            transport.abort()
                        except Exception as abort_exc:
                            self._ws_cleanup_failed = True
                            log.warning(f'飞书传输中止失败: {type(abort_exc).__name__}')
                    elif connection is not None:
                        self._ws_cleanup_failed = True
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()
            if self._ws_loop is loop:
                self._ws_loop = None

    def _request_ws_thread_shutdown(self) -> None:
        """请求飞书 WebSocket 线程退出"""
        self._ws_stop_requested = True
        loop = self._ws_loop
        if loop is None or loop.is_closed():
            return

        def shutdown() -> None:
            """在 WebSocket 事件循环中取消剩余任务"""
            if self._ws_client is not None:
                self._ws_client._auto_reconnect = False
            for task in asyncio.all_tasks(loop):
                task.cancel()

        try:
            loop.call_soon_threadsafe(shutdown)
        except RuntimeError:
            if not loop.is_closed():
                raise

    async def _stop_ws_client(self, *, force: bool = True) -> bool:
        """
        停止飞书 WebSocket 并校验资源已释放

        :param force: 是否强制停止
        :return:
        """
        self._request_ws_thread_shutdown()
        thread = self._ws_thread
        if thread is not None:
            await asyncio.to_thread(thread.join, _THREAD_STOP_TIMEOUT)
            if thread.is_alive():
                if force:
                    raise RuntimeError('飞书连接线程尚未退出，禁止释放账号租约并重新连接')
                return False
        cache_task = getattr(self, '_ws_cache_task', None)
        if cache_task is not None:
            await asyncio.gather(cache_task, return_exceptions=True)
        if getattr(self, '_ws_cleanup_failed', False):
            raise RuntimeError('飞书传输未确认关闭，禁止释放账号租约并重新连接')
        self._ws_thread = None
        self._ws_client = None
        self._ws_loop = None
        self._ws_session_id = None
        if force:
            self._ws_reconnecting_since = None
        return True

    async def stop(self) -> None:
        """停止飞书网关并关闭连接资源"""
        self._running = False
        try:
            await self._cancel_watchdog()
        finally:
            try:
                await self._stop_ws_client(force=True)
            finally:
                await self._close_http()

    def has_live_resources(self) -> bool:
        """判断当前线程或 SDK 曾保留的孤儿线程是否仍占用连接"""
        return (
            getattr(self, '_ws_cleanup_failed', False)
            or (self._ws_thread is not None and self._ws_thread.is_alive())
            or any(thread.is_alive() for thread in self._ws_orphan_threads)
        )
