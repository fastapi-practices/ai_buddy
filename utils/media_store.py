import asyncio
import base64
import hashlib

from typing import Any

from pydantic_ai_harness.tool_output_limits import OverflowStore
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.log import log
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.enums import AIBuddyConversationSource, AIBuddyObjectKind
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service
from backend.plugin.s3.crud.crud_storage import s3_storage_dao
from backend.plugin.s3.model import S3Storage
from backend.plugin.s3.utils.file_ops import get_bytes, put_bytes

_ATTACHMENT_PREFIX = 'ai_buddy/attachments/'
_OVERFLOW_PREFIX = 'ai_buddy/overflow/'


def _decode_binary_payload(data: str) -> tuple[bytes, str]:
    """
    在线程池内解码附件并计算对象键，避免大附件阻塞事件循环

    :param data: 输入数据
    :return:
    """
    raw = base64.b64decode(data)
    return raw, f'{_ATTACHMENT_PREFIX}{hashlib.sha256(raw).hexdigest()}'


class S3OverflowStore:
    """按用户隔离工具结果"""

    def __init__(self, storage: S3Storage, *, user_id: int) -> None:
        """
        绑定用户专属的工具输出溢出存储

        :param storage: S3 存储
        :param user_id: 当前用户 ID
        :return:
        """
        self._storage = storage
        self._user_id = user_id

    def _object_key(self, handle: str) -> str:
        """
        原始引用做哈希，避免路径清洗造成不同调用覆盖同一对象

        :param handle: 对象引用
        :return:
        """
        digest = hashlib.sha256(handle.encode()).hexdigest()
        return f'{_OVERFLOW_PREFIX}users/{self._user_id}/{digest}'

    async def write(self, key: str, data: bytes) -> str:
        """
        写入溢出内容

        :param key: 内容键
        :param data: 二进制内容
        :return:
        """
        object_key = self._object_key(key)
        await put_bytes(self._storage, object_key, data)
        # 登记失败只会让该对象暂不受保留期管理，不影响工具结果回读
        try:
            async with async_db_session.begin() as db:
                await ai_buddy_object_service.register_expiring(
                    db=db,
                    user_id=self._user_id,
                    kind=AIBuddyObjectKind.tool_output,
                    object_key=object_key,
                    storage_id=self._storage.id,
                    size=len(data),
                )
        except Exception as exc:
            log.warning(f'登记工具输出对象失败 key={object_key}: {exc}')
        return key

    async def read(self, handle: str) -> bytes:
        """
        读取溢出内容

        :param handle: 内容引用
        :return:
        """
        try:
            return await get_bytes(self._storage, self._object_key(handle))
        except Exception as exc:
            raise FileNotFoundError(handle) from exc


async def _load_default_storage() -> S3Storage | None:
    """读取默认 S3 存储"""
    try:
        async with async_db_session() as db:
            return await s3_storage_dao.get_default(db)
    except Exception as exc:
        log.warning(f'读取默认 S3 存储失败: {exc}')
        return None


async def _load_storage(storage_id: int) -> S3Storage | None:
    """
    按存储 ID 读取 S3 存储

    :param storage_id: 存储 ID
    :return:
    """
    try:
        async with async_db_session() as db:
            return await s3_storage_dao.get(db, storage_id)
    except Exception as exc:
        log.warning(f'读取 S3 存储失败 storage_id={storage_id}: {exc}')
        return None


async def get_overflow_store(*, user_id: int) -> OverflowStore | None:
    """
    获取当前用户的默认 S3 工具输出溢出存储

    :param user_id: 当前用户 ID
    :return:
    """
    storage = await _load_default_storage()
    if storage is None:
        return None
    return S3OverflowStore(storage, user_id=user_id)


async def _store_binaries(node: object, *, storage: S3Storage, written: list[dict[str, Any]]) -> object:
    """
    递归将内联二进制写入 S3

    :param node: 待处理数据
    :param storage: S3 存储
    :param written: 已写入对象记录
    :return:
    """
    if isinstance(node, list):
        if not node:
            return []
        return list(await asyncio.gather(*[_store_binaries(item, storage=storage, written=written) for item in node]))
    if not isinstance(node, dict):
        return node
    data = node.get('data')
    if node.get('kind') == 'binary' and isinstance(data, str):
        body, object_key = await asyncio.to_thread(_decode_binary_payload, data)
        await put_bytes(storage, object_key, body)
        written.append({'object_key': object_key, 'size': len(body), 'mime_type': node.get('media_type')})
        stored = {key: value for key, value in node.items() if key != 'data'}
        stored['object_key'] = object_key
        stored['storage_id'] = storage.id
        return stored
    return {key: await _store_binaries(value, storage=storage, written=written) for key, value in node.items()}


async def _restore_binaries(node: object, *, storage: S3Storage) -> object:
    """
    递归恢复 S3 二进制内容

    :param node: 待处理数据
    :param storage: S3 存储
    :return:
    """
    if isinstance(node, list):
        if not node:
            return []
        return list(await asyncio.gather(*[_restore_binaries(item, storage=storage) for item in node]))
    if not isinstance(node, dict):
        return node
    object_key = node.get('object_key')
    if node.get('kind') == 'binary' and isinstance(object_key, str) and 'data' not in node:
        stored_id = node.get('storage_id')
        source = await _load_storage(stored_id) if isinstance(stored_id, int) and stored_id != storage.id else storage
        if source is None:
            raise FileNotFoundError(object_key)
        raw = await get_bytes(source, object_key)
        restored = {key: value for key, value in node.items() if key not in {'object_key', 'storage_id'}}
        restored['data'] = (await asyncio.to_thread(base64.b64encode, raw)).decode()
        return restored
    return {key: await _restore_binaries(value, storage=storage) for key, value in node.items()}


async def _track_attachments(
    *, db: AsyncSession, conversation_id: str, storage_id: int, written: list[dict[str, Any]]
) -> None:
    """
    登记本次写入的附件并让对话引用，同一对象键只登记一次

    :param db: 数据库会话
    :param conversation_id: 对话 ID
    :param storage_id: 对象存储 ID
    :param written: 本次写入的附件
    :return:
    """
    conversation = await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
    if conversation is None:
        return
    for item in {entry['object_key']: entry for entry in written}.values():
        await ai_buddy_object_service.track_conversation_attachment(
            db=db, user_id=conversation.user_id, conversation_id=conversation_id, storage_id=storage_id, **item
        )


def _has_binary(node: object) -> bool:
    """
    判断消息树中是否含有二进制附件

    :param node: JSON 形态的消息树
    :return:
    """
    if isinstance(node, list):
        return any(_has_binary(item) for item in node)
    if isinstance(node, dict):
        return node.get('kind') == 'binary' or any(_has_binary(value) for value in node.values())
    return False


async def _is_local_conversation(*, conversation_id: str, db: AsyncSession | None) -> bool:
    """
    判断对话是否以本机为事实源，本机会话的附件不进入云端对象存储

    :param conversation_id: 对话 ID
    :param db: 调用方事务，所属对话尚未提交时必须传入
    :return:
    """
    if db is not None:
        conversation = await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
    else:
        async with async_db_session() as own_db:
            conversation = await ai_buddy_conversation_dao.get_by_conversation_id(own_db, conversation_id)
    return conversation is not None and conversation.source == AIBuddyConversationSource.local


async def _encode_media_payload(
    payload: object, *, conversation_id: str | None = None, db: AsyncSession | None = None
) -> object:
    """
    将聊天二进制附件写入 S3，消息 JSON 只保留对象键，并让所属对话引用这些附件；以本机为事实源的对话保持内联，不上云

    :param payload: JSON 形态的消息树
    :param conversation_id: 所属对话 ID，为空时只写入不登记引用
    :param db: 调用方事务，所属对话尚未提交时必须传入；为空时登记引用会使用独立事务
    :return:
    """
    if (
        conversation_id
        and _has_binary(payload)
        and await _is_local_conversation(conversation_id=conversation_id, db=db)
    ):
        return payload
    storage = await _load_default_storage()
    if storage is None:
        return payload
    written: list[dict[str, Any]] = []
    try:
        encoded = await _store_binaries(payload, storage=storage, written=written)
    except Exception as exc:
        log.warning(f'写入聊天附件失败，改为内联保存: {exc}')
        return payload
    if conversation_id and written:
        if db is not None:
            await _track_attachments(db=db, conversation_id=conversation_id, storage_id=storage.id, written=written)
            return encoded
        # 登记失败只会让附件暂不受回收管理，不影响消息保存
        try:
            async with async_db_session.begin() as own_db:
                await _track_attachments(
                    db=own_db, conversation_id=conversation_id, storage_id=storage.id, written=written
                )
        except Exception as exc:
            log.warning(f'登记聊天附件引用失败 conversation_id={conversation_id}: {exc}')
    return encoded


async def _decode_media_payload(payload: object) -> object:
    """
    按对象键从 S3 还原聊天附件

    :param payload: JSON 形态的消息树
    :return:
    """
    storage = await _load_default_storage()
    if storage is None:
        return payload
    return await _restore_binaries(payload, storage=storage)


async def dump_model_message_payloads(messages: object) -> list[Any]:
    """
    在线程池序列化模型消息，避免大图 base64 卡住事件循环

    :param messages: 模型消息对象
    :return:
    """
    payload = await asyncio.to_thread(to_jsonable_python, messages, by_alias=True)
    if not isinstance(payload, list):
        raise TypeError('模型消息序列化结果必须是列表')
    return payload


async def encode_model_message_payloads(
    payloads: list[Any], *, conversation_id: str | None = None, db: AsyncSession | None = None
) -> list[Any]:
    """
    将模型消息中的二进制附件写入 S3

    :param payloads: 模型消息 JSON 列表
    :param conversation_id: 所属对话 ID，用于登记附件引用
    :param db: 调用方事务，所属对话尚未提交时必须传入
    :return:
    """
    encoded = await _encode_media_payload(payloads, conversation_id=conversation_id, db=db)
    if not isinstance(encoded, list):
        return payloads
    return encoded


async def decode_model_message_payloads(payloads: list[Any]) -> list[Any]:
    """
    还原模型消息 JSON 中的 S3 附件

    :param payloads: 模型消息 JSON 列表
    :return:
    """
    decoded = await _decode_media_payload(payloads)
    if not isinstance(decoded, list):
        return payloads
    return decoded
