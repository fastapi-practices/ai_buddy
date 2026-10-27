import asyncio
import base64
import binascii
import json
import logging
import os
import sys
import time

from typing import Any

import httpx2

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.database.redis import redis_client
from backend.plugin.ai_buddy.enums import AIBuddyChannelQrcodeStatus, AIBuddyChannelType

_SESSION_TTL_SECONDS = 600
_WECHAT_ILINK_BASE = 'https://ilinkai.weixin.qq.com'
_DINGTALK_REG_BASE = 'https://oapi.dingtalk.com'
_WECOM_QC_GENERATE = 'https://work.weixin.qq.com/ai/qc/generate'
_WECOM_QC_QUERY = 'https://work.weixin.qq.com/ai/qc/query_result'
_WECOM_QC_PAGE = 'https://work.weixin.qq.com/ai/qc/gen'
_WECOM_QC_SOURCE = 'wecom_cli_external'
_QQ_HOST = 'q.qq.com'
_BROWSER_HEADERS = {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
    'User-Agent': 'Mozilla/5.0 AIBuddy/1.0',
}
_QRCODE_TYPES = frozenset({
    AIBuddyChannelType.feishu,
    AIBuddyChannelType.wechat,
    AIBuddyChannelType.wecom,
    AIBuddyChannelType.dingtalk,
    AIBuddyChannelType.qq,
})
_CHANNEL_NAMES = {
    AIBuddyChannelType.wechat: '微信',
    AIBuddyChannelType.qq: 'QQ',
    AIBuddyChannelType.wecom: '企业微信',
    AIBuddyChannelType.feishu: '飞书',
    AIBuddyChannelType.dingtalk: '钉钉',
    AIBuddyChannelType.telegram: 'Telegram',
    AIBuddyChannelType.discord: 'Discord',
}
CHANNEL_BIND_OPTIONS: tuple[dict[str, Any], ...] = (
    {'type': AIBuddyChannelType.feishu, 'qrcode': True, 'config_keys': ['app_id', 'app_secret']},
    {'type': AIBuddyChannelType.wechat, 'qrcode': True, 'config_keys': ['bot_token']},
    {'type': AIBuddyChannelType.wecom, 'qrcode': True, 'config_keys': ['bot_id', 'secret']},
    {'type': AIBuddyChannelType.dingtalk, 'qrcode': True, 'config_keys': ['app_key', 'app_secret']},
    {'type': AIBuddyChannelType.qq, 'qrcode': True, 'config_keys': ['app_id', 'app_secret']},
    {'type': AIBuddyChannelType.telegram, 'qrcode': False, 'config_keys': ['bot_token']},
    {'type': AIBuddyChannelType.discord, 'qrcode': False, 'config_keys': ['bot_token']},
)
_FEISHU_TASKS: dict[str, asyncio.Task[None]] = {}
_FEISHU_QR_READY_TIMEOUT = 20
_FEISHU_LOG_FILTER_INSTALLED = False
_PATCH_SESSION_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then return false end
local payload = cjson.decode(raw)
local fields = cjson.decode(ARGV[1])
local status = payload.status
if fields.status and (status == 'confirmed' or status == 'expired' or status == 'error') then
    return raw
end
for key, value in pairs(fields) do payload[key] = value end
if payload.status == 'confirmed' or payload.status == 'expired' or payload.status == 'error' then
    payload.platform_token = cjson.null
    payload.bind_key = cjson.null
end
local ttl = redis.call('TTL', KEYS[1])
if fields.expire_at then ttl = math.max(ttl, fields.expire_at - tonumber(ARGV[2]) + 60) end
if ttl <= 0 then return false end
local updated = cjson.encode(payload)
redis.call('SET', KEYS[1], updated, 'EX', ttl, 'XX')
return updated
"""


class _FeishuPendingLogFilter(logging.Filter):
    """飞书设备码等待扫码时按规范返回 400，不记为请求失败"""

    @staticmethod
    def filter(record: logging.LogRecord) -> bool:
        """
        过滤飞书设备码等待阶段的预期错误日志

        :param record: 日志记录
        :return:
        """
        message = record.getMessage()
        if 'oauth/v1/app/registration' not in message:
            return True
        return '400 Bad Request' not in message


def channel_display_name(channel_type: AIBuddyChannelType) -> str:
    """
    通道类型展示名

    :param channel_type: 通道类型
    :return:
    """
    return _CHANNEL_NAMES[channel_type]


def supports_channel_qrcode(channel_type: AIBuddyChannelType) -> bool:
    """
    是否支持扫码绑定

    :param channel_type: 通道类型
    :return:
    """
    return channel_type in _QRCODE_TYPES


def _qrcode_session_key(session_id: str) -> str:
    """
    扫码会话 Redis 键

    :param session_id: 扫码会话 ID
    :return:
    """
    return f'{settings.PLUGIN_REDIS_PREFIX}:ai_buddy:channel_qrcode:{session_id}'


async def save_qrcode_session(session_id: str, payload: dict[str, Any]) -> None:
    """
    保存扫码会话

    :param session_id: 扫码会话 ID
    :param payload: 会话内容
    :return:
    """
    ttl = max(_SESSION_TTL_SECONDS, int(payload.get('expire_at') or 0) - int(time.time()) + 60)
    await redis_client.set(_qrcode_session_key(session_id), json.dumps(payload, ensure_ascii=False), ex=ttl)


async def load_qrcode_session(session_id: str) -> dict[str, Any] | None:
    """
    读取扫码会话

    :param session_id: 扫码会话 ID
    :return:
    """
    raw = await redis_client.get(_qrcode_session_key(session_id))
    if not raw:
        return None
    data = json.loads(raw)
    return data if isinstance(data, dict) else None


async def delete_qrcode_session(session_id: str) -> None:
    """
    删除扫码会话

    :param session_id: 扫码会话 ID
    :return:
    """
    await redis_client.delete(_qrcode_session_key(session_id))


async def cancel_feishu_qrcode(session_id: str) -> None:
    """
    取消飞书扫码后台轮询

    :param session_id: 扫码会话 ID
    :return:
    """
    task = _FEISHU_TASKS.pop(session_id, None)
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def patch_qrcode_session(session_id: str, **fields: Any) -> dict[str, Any]:
    """
    更新扫码会话字段

    :param session_id: 扫码会话 ID
    :param fields: 要覆盖的字段
    :return:
    """
    raw = await redis_client.eval(
        _PATCH_SESSION_SCRIPT,
        1,
        _qrcode_session_key(session_id),
        json.dumps(fields, ensure_ascii=False),
        int(time.time()),
    )
    if not raw:
        raise errors.NotFoundError(msg='扫码会话不存在或已过期')
    return json.loads(raw)


def _platform_code(payload: dict[str, Any], key: str) -> int:
    """
    读取平台返回码。0 表示成功，不能用 `or` 判断，否则成功码会被当成失败

    :param payload: 平台响应
    :param key: 返回码字段
    :return:
    """
    if not isinstance(payload, dict):
        return -1
    raw = payload.get(key)
    if raw is None:
        return -1
    if isinstance(raw, str) and not raw.strip():
        return -1
    try:
        return int(raw)
    except (TypeError, ValueError):
        return -1


async def request_wechat_qrcode() -> tuple[str, str]:
    """向微信 iLink 申请登录二维码"""
    async with httpx2.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f'{_WECHAT_ILINK_BASE}/ilink/bot/get_bot_qrcode',
            params={'bot_type': '3'},
            json={'local_token_list': []},
        )
        if response.status_code >= 400:
            response = await client.get(
                f'{_WECHAT_ILINK_BASE}/ilink/bot/get_bot_qrcode',
                params={'bot_type': '3'},
            )
        response.raise_for_status()
        data = response.json()
    data = data if isinstance(data, dict) else {}
    token = str(data.get('qrcode') or '')
    image = str(data.get('qrcode_img_content') or data.get('qrcode_img_url') or '')
    if not token or not image:
        raise errors.RequestError(msg='微信二维码获取失败')
    return token, image


async def _request_wechat_qrcode_status(token: str) -> dict[str, Any]:
    """
    查询微信扫码状态

    :param token: 微信二维码令牌
    :return:
    """
    async with httpx2.AsyncClient(timeout=8.0) as client:
        try:
            response = await client.get(
                f'{_WECHAT_ILINK_BASE}/ilink/bot/get_qrcode_status',
                params={'qrcode': token},
                headers={'iLink-App-ClientVersion': '1'},
            )
            response.raise_for_status()
            data = response.json()
        except httpx2.TimeoutException:
            return {'status': 'wait'}
    return data if isinstance(data, dict) else {'status': 'wait'}


def _map_wechat_status(raw: str) -> AIBuddyChannelQrcodeStatus:
    """
    映射微信扫码状态

    :param raw: 平台原始状态
    :return:
    """
    if raw in {'scaned', 'scanned'}:
        return AIBuddyChannelQrcodeStatus.scanned
    if raw == 'confirmed':
        return AIBuddyChannelQrcodeStatus.confirmed
    if raw == 'expired':
        return AIBuddyChannelQrcodeStatus.expired
    if raw in {'need_verifycode', 'verify_code_blocked'}:
        return AIBuddyChannelQrcodeStatus.error
    return AIBuddyChannelQrcodeStatus.wait


async def _cancel_task(task: asyncio.Task[Any]) -> None:
    """
    取消并等待指定后台任务结束

    :param task: 后台任务
    :return:
    """
    if task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _run_feishu_register(  # ruff: ignore[complex-structure]
    *, session_id: str, ready: asyncio.Event, register: Any
) -> None:
    """
    维护 SDK 注册任务和回调写入任务，在取消或过期时一起回收

    :param session_id: 会话 ID
    :param ready: 就绪事件
    :param register: 注册回调
    :return:
    """
    loop = asyncio.get_running_loop()
    qr_tasks: list[asyncio.Task[None]] = []
    accepting_qr = True

    def on_qr_code(info: dict[str, Any]) -> None:
        """
        接收飞书二维码并更新扫码会话

        :param info: 二维码信息
        :return:
        """
        url = str(info.get('url') or '')
        expire_in = int(info.get('expire_in') or info.get('expireIn') or 300)

        async def _save_and_ready() -> None:
            """将 SDK 线程回调中的状态写入切回事件循环后再通知等待者"""
            try:
                await patch_qrcode_session(
                    session_id,
                    status=AIBuddyChannelQrcodeStatus.wait.value,
                    qrcode_url=url,
                    expire_at=int(time.time()) + expire_in,
                )
            finally:
                ready.set()

        def schedule_qr() -> None:
            """调度飞书应用注册二维码生成"""
            if accepting_qr:
                qr_tasks.append(asyncio.create_task(_save_and_ready()))

        loop.call_soon_threadsafe(schedule_qr)

    register_task = asyncio.create_task(
        register(
            on_qr_code=on_qr_code,
            create_only=True,
            source='ai-buddy',
            app_preset={'name': '{user}的 AI Buddy', 'desc': '由 AI Buddy 扫码创建'},
            addons={
                'scopes': {'tenant': ['im:message:send_as_bot', 'im:message']},
                'events': {'items': {'tenant': ['im.message.receive_v1']}},
                'callbacks': {'items': ['card.action.trigger']},
            },
        )
    )
    try:
        while not register_task.done():
            payload = await load_qrcode_session(session_id)
            if payload is None:
                await _cancel_task(register_task)
                return
            if int(payload.get('expire_at') or 0) <= int(time.time()):
                await _cancel_task(register_task)
                await patch_qrcode_session(
                    session_id,
                    status=AIBuddyChannelQrcodeStatus.expired.value,
                    error='二维码已过期，请重新扫码',
                )
                ready.set()
                return
            await asyncio.wait({register_task}, timeout=2)
        result = await register_task
        if qr_tasks:
            await asyncio.gather(*qr_tasks)
        result = result if isinstance(result, dict) else {}
        app_id = str(result.get('client_id') or result.get('app_id') or result.get('open_id') or '').strip()
        app_secret = str(
            result.get('client_secret') or result.get('app_secret') or result.get('open_key') or ''
        ).strip()
        if not app_id or not app_secret:
            raise errors.RequestError(msg='飞书扫码成功但未返回凭证')
        await patch_qrcode_session(
            session_id,
            status=AIBuddyChannelQrcodeStatus.confirmed.value,
            config={'app_id': app_id, 'app_secret': app_secret},
        )
        ready.set()
    except Exception:
        try:
            await patch_qrcode_session(
                session_id,
                status=AIBuddyChannelQrcodeStatus.error.value,
                error='飞书扫码失败，请重试或手动填写凭证',
            )
        except errors.NotFoundError:
            pass
        ready.set()
    finally:
        accepting_qr = False
        register_task.cancel()
        for task in qr_tasks:
            task.cancel()
        await asyncio.gather(register_task, *qr_tasks, return_exceptions=True)


async def start_feishu_qrcode(*, session_id: str) -> tuple[str, int]:  # ruff: ignore[complex-structure]
    """
    启动飞书扫码建应用，返回二维码链接和有效秒数

    :param session_id: 扫码会话 ID
    :return:
    """
    try:
        import lark_oapi as lark
    except ImportError as exc:
        raise errors.RequestError(msg='飞书扫码不可用，请手动填写 App ID 和 App Secret') from exc
    register = getattr(lark, 'aregister_app', None)
    if register is None:
        raise errors.RequestError(msg='飞书扫码不可用，请手动填写 App ID 和 App Secret')
    global _FEISHU_LOG_FILTER_INSTALLED
    if not _FEISHU_LOG_FILTER_INSTALLED:
        log_filter = _FeishuPendingLogFilter()
        for name in ('httpx', 'httpx2', 'httpcore'):
            logging.getLogger(name).addFilter(log_filter)
        _FEISHU_LOG_FILTER_INSTALLED = True
    ready = asyncio.Event()
    task = asyncio.create_task(_run_feishu_register(session_id=session_id, ready=ready, register=register))
    _FEISHU_TASKS[session_id] = task

    def on_finished(finished: asyncio.Task[None]) -> None:
        """
        处理飞书扫码后台任务完成状态

        :param finished: 完成任务
        :return:
        """
        if _FEISHU_TASKS.get(session_id) is finished:
            _FEISHU_TASKS.pop(session_id, None)
        if not finished.cancelled() and (exc := finished.exception()) is not None:
            log.warning(f'飞书扫码后台任务异常: {type(exc).__name__}')
        ready.set()

    task.add_done_callback(on_finished)
    try:
        await asyncio.wait_for(ready.wait(), timeout=_FEISHU_QR_READY_TIMEOUT)
    except TimeoutError as exc:
        await cancel_feishu_qrcode(session_id)
        raise errors.RequestError(msg='飞书二维码生成超时') from exc
    except asyncio.CancelledError:
        await cancel_feishu_qrcode(session_id)
        raise
    payload = await load_qrcode_session(session_id)
    url = str((payload or {}).get('qrcode_url') or '')
    if not url:
        await cancel_feishu_qrcode(session_id)
        raise errors.RequestError(msg=str((payload or {}).get('error') or '飞书二维码生成失败'))
    expire_at = int((payload or {}).get('expire_at') or (time.time() + 300))
    return url, max(expire_at - int(time.time()), 0)


async def request_wecom_qrcode() -> tuple[str, str]:
    """向企业微信申请扫码建机器人二维码"""
    async with httpx2.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            _WECOM_QC_GENERATE,
            params={'source': _WECOM_QC_SOURCE, 'plat': {'darwin': 1, 'win32': 2}.get(sys.platform, 3)},
        )
        response.raise_for_status()
        payload = response.json()
    data = payload.get('data') if isinstance(payload, dict) else None
    data = data if isinstance(data, dict) else {}
    scode = str(data.get('scode') or '')
    auth_url = str(data.get('auth_url') or '')
    if not scode:
        raise errors.RequestError(msg='企业微信二维码获取失败')
    qrcode_url = auth_url or f'{_WECOM_QC_PAGE}?source={_WECOM_QC_SOURCE}&scode={scode}'
    return scode, qrcode_url


async def _request_wecom_qrcode_status(scode: str) -> dict[str, Any]:
    """
    查询企业微信扫码状态

    :param scode: 企业微信扫码会话码
    :return:
    """
    async with httpx2.AsyncClient(timeout=8.0) as client:
        try:
            response = await client.get(_WECOM_QC_QUERY, params={'scode': scode})
            response.raise_for_status()
            payload = response.json()
        except httpx2.TimeoutException:
            return {}
    data = payload.get('data') if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}


async def request_dingtalk_qrcode() -> tuple[str, str, int]:
    """向钉钉申请扫码注册二维码"""
    async with httpx2.AsyncClient(timeout=15.0, headers=_BROWSER_HEADERS) as client:
        init = await client.post(f'{_DINGTALK_REG_BASE}/app/registration/init', json={'source': 'openClaw'})
        init.raise_for_status()
        init_data = init.json()
        init_data = init_data if isinstance(init_data, dict) else {}
        if _platform_code(init_data, 'errcode') != 0:
            raise errors.RequestError(msg='钉钉扫码初始化失败')
        nonce = str(init_data.get('nonce') or '').strip()
        if not nonce:
            raise errors.RequestError(msg='钉钉扫码初始化失败')
        begin = await client.post(f'{_DINGTALK_REG_BASE}/app/registration/begin', json={'nonce': nonce})
        begin.raise_for_status()
        begin_data = begin.json()
        begin_data = begin_data if isinstance(begin_data, dict) else {}
        if _platform_code(begin_data, 'errcode') != 0:
            raise errors.RequestError(msg='钉钉二维码获取失败')
    device_code = str(begin_data.get('device_code') or '').strip()
    url = str(begin_data.get('verification_uri_complete') or '').strip()
    expire_in = int(begin_data.get('expires_in') or 7200)
    if not device_code or not url:
        raise errors.RequestError(msg='钉钉二维码获取失败')
    return device_code, url, expire_in


async def _request_dingtalk_qrcode_status(device_code: str) -> dict[str, Any]:
    """
    查询钉钉扫码状态

    :param device_code: 钉钉设备码
    :return:
    """
    async with httpx2.AsyncClient(timeout=8.0, headers=_BROWSER_HEADERS) as client:
        try:
            response = await client.post(
                f'{_DINGTALK_REG_BASE}/app/registration/poll',
                json={'device_code': device_code},
            )
            response.raise_for_status()
            data = response.json()
        except httpx2.TimeoutException:
            return {'status': 'WAITING'}
    return data if isinstance(data, dict) else {'status': 'WAITING'}


async def request_qq_qrcode() -> tuple[str, str, str]:
    """向 QQ 开放平台申请扫码绑定任务"""
    bind_key = base64.b64encode(os.urandom(32)).decode('ascii')
    async with httpx2.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f'https://{_QQ_HOST}/lite/create_bind_task',
            json={'key': bind_key},
            headers=_BROWSER_HEADERS,
        )
        response.raise_for_status()
        payload = response.json()
    if _platform_code(payload, 'retcode') != 0:
        raise errors.RequestError(msg='QQ 扫码任务创建失败')
    data = payload.get('data')
    task_id = str(data.get('task_id') or '') if isinstance(data, dict) else ''
    if not task_id:
        raise errors.RequestError(msg='QQ 扫码任务创建失败')
    url = f'https://{_QQ_HOST}/qqbot/openclaw/connect.html?task_id={task_id}&source=ai-buddy&_wv=2'
    return task_id, bind_key, url


async def _request_qq_qrcode_status(task_id: str) -> dict[str, Any]:
    """
    查询 QQ 扫码绑定状态

    :param task_id: QQ 绑定任务 ID
    :return:
    """
    async with httpx2.AsyncClient(timeout=8.0) as client:
        try:
            response = await client.post(
                f'https://{_QQ_HOST}/lite/poll_bind_result',
                json={'task_id': task_id},
                headers=_BROWSER_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx2.TimeoutException:
            return {'retcode': 0, 'data': {'status': 1}}
    return payload if isinstance(payload, dict) else {'retcode': 0, 'data': {'status': 1}}


def _decrypt_qq_secret(*, encrypted: str, key_b64: str) -> str:
    """
    解密 QQ 扫码返回的 AppSecret

    :param encrypted: 平台返回的密文
    :param key_b64: 创建任务时的绑定密钥
    :return:
    """
    try:
        key = base64.b64decode(key_b64, validate=True)
        blob = base64.b64decode(encrypted, validate=True)
        if len(key) != 32 or len(blob) < 29:
            raise ValueError('invalid encrypted credential length')
        secret = AESGCM(key).decrypt(blob[:12], blob[12:], None).decode('utf-8')
        if not secret.strip():
            raise ValueError('empty credential')
    except (binascii.Error, InvalidTag, ValueError, UnicodeDecodeError) as exc:
        raise errors.RequestError(msg='QQ 扫码凭证校验失败，请重新扫码') from exc
    return secret


async def poll_wechat_qrcode(*, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    查询微信扫码结果并更新会话凭证

    :param session_id: 扫码会话 ID
    :param payload: 当前扫码会话数据
    :return:
    """
    token = str(payload.get('platform_token') or '')
    if not token:
        raise errors.RequestError(msg='微信扫码会话无效')
    data = await _request_wechat_qrcode_status(token)
    raw_status = str(data.get('status') or 'wait')
    status = _map_wechat_status(raw_status)
    fields: dict[str, Any] = {'status': status.value}
    if status == AIBuddyChannelQrcodeStatus.confirmed:
        bot_token = str(data.get('bot_token') or '')
        if not bot_token:
            raise errors.RequestError(msg='微信扫码成功但未返回凭证')
        fields['config'] = {
            'bot_token': bot_token,
            'ilink_bot_id': data.get('ilink_bot_id'),
            'ilink_user_id': data.get('ilink_user_id'),
            'baseurl': data.get('baseurl'),
        }
    elif status == AIBuddyChannelQrcodeStatus.error:
        fields['error'] = '微信扫码需要验证码，请重试或改为手动填写'
    elif status == AIBuddyChannelQrcodeStatus.expired:
        fields['error'] = '二维码已过期，请重新扫码'
    return await patch_qrcode_session(session_id, **fields)


async def poll_wecom_qrcode(*, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    查询企业微信扫码结果并更新会话凭证

    :param session_id: 扫码会话 ID
    :param payload: 当前扫码会话数据
    :return:
    """
    scode = str(payload.get('platform_token') or '')
    if not scode:
        raise errors.RequestError(msg='企业微信扫码会话无效')
    data = await _request_wecom_qrcode_status(scode)
    status = str(data.get('status') or '').lower()
    if status == 'expired':
        return await patch_qrcode_session(
            session_id, status=AIBuddyChannelQrcodeStatus.expired.value, error='二维码已过期，请重新扫码'
        )
    if status in {'error', 'fail', 'failed'}:
        return await patch_qrcode_session(
            session_id, status=AIBuddyChannelQrcodeStatus.error.value, error='企业微信扫码失败，请重新扫码'
        )
    if status != 'success':
        return payload
    bot_info = data.get('bot_info') if isinstance(data.get('bot_info'), dict) else {}
    bot_id = str(bot_info.get('botid') or '')
    secret = str(bot_info.get('secret') or '')
    if not bot_id or not secret:
        raise errors.RequestError(msg='企业微信扫码成功但未返回凭证')
    return await patch_qrcode_session(
        session_id,
        status=AIBuddyChannelQrcodeStatus.confirmed.value,
        config={
            'bot_id': bot_id,
            'secret': secret,
            'websocket_url': 'wss://openws.work.weixin.qq.com',
        },
    )


async def poll_dingtalk_qrcode(*, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    查询钉钉扫码结果并更新会话凭证

    :param session_id: 扫码会话 ID
    :param payload: 当前扫码会话数据
    :return:
    """
    device_code = str(payload.get('platform_token') or '')
    if not device_code:
        raise errors.RequestError(msg='钉钉扫码会话无效')
    data = await _request_dingtalk_qrcode_status(device_code)
    if 'errcode' in data and _platform_code(data, 'errcode') != 0:
        raise errors.RequestError(msg='钉钉扫码查询失败，请重试')
    status = str(data.get('status') or 'WAITING').upper()
    if status == 'SUCCESS':
        app_key = str(data.get('client_id') or data.get('app_key') or data.get('key') or '').strip()
        app_secret = str(data.get('client_secret') or data.get('app_secret') or data.get('secret') or '').strip()
        if not app_key or not app_secret:
            raise errors.RequestError(msg='钉钉扫码成功但未返回凭证')
        return await patch_qrcode_session(
            session_id,
            status=AIBuddyChannelQrcodeStatus.confirmed.value,
            config={'app_key': app_key, 'app_secret': app_secret},
        )
    if status == 'EXPIRED':
        return await patch_qrcode_session(
            session_id,
            status=AIBuddyChannelQrcodeStatus.expired.value,
            error='二维码已过期，请重新扫码',
        )
    if status in {'FAIL', 'FAILED', 'ERROR', 'DENIED'}:
        return await patch_qrcode_session(
            session_id,
            status=AIBuddyChannelQrcodeStatus.error.value,
            error='钉钉扫码失败，请重新扫码',
        )
    return payload


async def poll_qq_qrcode(*, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """
    查询QQ扫码结果并更新会话凭证

    :param session_id: 扫码会话 ID
    :param payload: 当前扫码会话数据
    :return:
    """
    task_id = str(payload.get('platform_token') or '')
    bind_key = str(payload.get('bind_key') or '')
    if not task_id or not bind_key:
        raise errors.RequestError(msg='QQ 扫码会话无效')
    result = await _request_qq_qrcode_status(task_id)
    if _platform_code(result, 'retcode') != 0:
        raise errors.RequestError(msg='QQ 扫码查询失败，请重试')
    data = result.get('data') if isinstance(result.get('data'), dict) else {}
    status = int(data.get('status') or 0)
    if status == 2:
        app_id = str(data.get('bot_appid') or '')
        encrypted = str(data.get('bot_encrypt_secret') or '')
        if not app_id or not encrypted:
            raise errors.RequestError(msg='QQ 扫码成功但未返回凭证')
        return await patch_qrcode_session(
            session_id,
            status=AIBuddyChannelQrcodeStatus.confirmed.value,
            config={
                'app_id': app_id,
                'app_secret': _decrypt_qq_secret(encrypted=encrypted, key_b64=bind_key),
            },
        )
    if status == 3:
        return await patch_qrcode_session(
            session_id,
            status=AIBuddyChannelQrcodeStatus.expired.value,
            error='二维码已过期，请重新扫码',
        )
    return payload
