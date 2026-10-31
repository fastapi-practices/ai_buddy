import asyncio
import base64
import hashlib
import re

from typing import Any

from pydantic_ai_harness.tool_output_limits import OverflowStore
from pydantic_core import to_jsonable_python
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.log import log
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.crud.crud_conversation import ai_buddy_conversation_dao
from backend.plugin.ai_buddy.crud.crud_object import ai_buddy_object_dao
from backend.plugin.ai_buddy.enums import AIBuddyConversationSource, AIBuddyObjectKind, AIBuddyObjectLocation
from backend.plugin.ai_buddy.model.conversation import AIBuddyConversation
from backend.plugin.ai_buddy.service.object_service import ai_buddy_object_service
from backend.plugin.s3.crud.crud_storage import s3_storage_dao
from backend.plugin.s3.model import S3Storage
from backend.plugin.s3.utils.file_ops import get_bytes, put_bytes

_ATTACHMENT_PREFIX = 'ai_buddy/attachments/'
_ATTACHMENT_KEY = re.compile(rf'{_ATTACHMENT_PREFIX}(?:[0-9]+/)?[0-9a-f]{{64}}')
_OVERFLOW_PREFIX = 'ai_buddy/overflow/'


def attachment_object_key(*, digest: str, user_id: int | None) -> str:
    """
    构建聊天附件对象键，按用户隔离，避免相同内容在不同用户之间共用同一条对象记录

    :param digest: 内容 SHA-256 摘要
    :param user_id: 附件所属用户 ID，为空时使用不区分用户的键
    :return:
    """
    return f'{_ATTACHMENT_PREFIX}{digest}' if user_id is None else f'{_ATTACHMENT_PREFIX}{user_id}/{digest}'


def _decode_binary_payload(data: str, user_id: int | None) -> tuple[bytes, str]:
    """
    在线程池内解码附件并计算对象键，避免大附件阻塞事件循环

    :param data: 输入数据
    :param user_id: 附件所属用户 ID
    :return:
    """
    raw = base64.b64decode(data)
    return raw, attachment_object_key(digest=hashlib.sha256(raw).hexdigest(), user_id=user_id)


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


async def _store_binaries(
    node: object, *, storage: S3Storage, written: list[dict[str, Any]], user_id: int | None
) -> object:
    """
    递归将内联二进制写入 S3

    :param node: 待处理数据
    :param storage: S3 存储
    :param written: 已写入对象记录
    :param user_id: 附件所属用户 ID
    :return:
    """
    if isinstance(node, list):
        if not node:
            return []
        return list(
            await asyncio.gather(*[
                _store_binaries(item, storage=storage, written=written, user_id=user_id) for item in node
            ])
        )
    if not isinstance(node, dict):
        return node
    data = node.get('data')
    if node.get('kind') == 'binary' and isinstance(data, str):
        body, object_key = await asyncio.to_thread(_decode_binary_payload, data, user_id)
        await put_bytes(storage, object_key, body)
        written.append({'object_key': object_key, 'size': len(body), 'mime_type': node.get('media_type')})
        stored = {key: value for key, value in node.items() if key != 'data'}
        stored['object_key'] = object_key
        stored['storage_id'] = storage.id
        return stored
    return {
        key: await _store_binaries(value, storage=storage, written=written, user_id=user_id)
        for key, value in node.items()
    }


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
    # 持久化的消息里也会有模型和 MCP 写入的任意 JSON，只还原由内容摘要命名的附件键，
    # 不能按消息里自带的键读取其他用户的产物、知识或技能对象
    if (
        node.get('kind') == 'binary'
        and isinstance(object_key, str)
        and _ATTACHMENT_KEY.fullmatch(object_key)
        and 'data' not in node
    ):
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


def _collect_attachment_refs(node: object, found: set[tuple[int, str]]) -> None:
    """
    递归收集消息树中由服务端写入的附件引用

    :param node: JSON 形态的消息树
    :param found: 收集到的（存储 ID，对象键）
    :return:
    """
    if isinstance(node, list):
        for item in node:
            _collect_attachment_refs(item, found)
    elif isinstance(node, dict):
        object_key, storage_id = node.get('object_key'), node.get('storage_id')
        if (
            node.get('kind') == 'binary'
            and isinstance(object_key, str)
            and _ATTACHMENT_KEY.fullmatch(object_key)
            and isinstance(storage_id, int)
        ):
            found.add((storage_id, object_key))
        for value in node.values():
            _collect_attachment_refs(value, found)


async def track_copied_attachments(
    *, db: AsyncSession, conversation_id: str, user_id: int, payloads: list[Any]
) -> None:
    """
    让复制出的对话引用消息里的既有附件，源对话被删除后附件仍有持有者

    :param db: 数据库会话
    :param conversation_id: 新对话 ID
    :param user_id: 新对话所属用户 ID
    :param payloads: 复制的模型消息 JSON
    :return:
    """
    found: set[tuple[int, str]] = set()
    _collect_attachment_refs(payloads, found)
    for storage_id, object_key in sorted(found):
        stored = await ai_buddy_object_dao.get_by_key(db, AIBuddyObjectLocation.s3.value, storage_id, object_key)
        # 只引用本人的对象，旧版共享键的对象可能属于他人
        if stored is not None and stored.user_id == user_id:
            await ai_buddy_object_service.add_reference(
                db=db, obj=stored, owner_type='conversation', owner_id=conversation_id, actor_id=user_id
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


async def _load_conversation(*, conversation_id: str, db: AsyncSession | None) -> AIBuddyConversation | None:
    """
    读取附件所属对话，所属对话尚未提交时必须使用调用方事务

    :param conversation_id: 对话 ID
    :param db: 调用方事务
    :return:
    """
    if db is not None:
        return await ai_buddy_conversation_dao.get_by_conversation_id(db, conversation_id)
    async with async_db_session() as own_db:
        return await ai_buddy_conversation_dao.get_by_conversation_id(own_db, conversation_id)


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
    owner_id = None
    if conversation_id and _has_binary(payload):
        conversation = await _load_conversation(conversation_id=conversation_id, db=db)
        # 以本机为事实源的对话附件保持内联，不进入云端对象存储
        if conversation is not None and conversation.source == AIBuddyConversationSource.local:
            return payload
        owner_id = None if conversation is None else conversation.user_id
    storage = await _load_default_storage()
    if storage is None:
        return payload
    written: list[dict[str, Any]] = []
    try:
        encoded = await _store_binaries(payload, storage=storage, written=written, user_id=owner_id)
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
