import asyncio
import base64
import hashlib
import json
import time

from collections.abc import Awaitable, Callable
from operator import itemgetter
from typing import Any
from uuid import uuid4

from cryptography.fernet import Fernet
from pydantic import SecretStr

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store
from backend.plugin.ai_buddy.enums import AIBuddyInputQuestionKind, AIBuddyInputRequestKind, AIBuddyInputRequestStatus
from backend.plugin.ai_buddy.schema.input_request import AIBuddyInputQuestion, ResolveAIBuddyInputRequestParam

_INPUT_TTL = 30 * 60
_RESOLVE_INPUT = """
local pending = redis.call('get', KEYS[1])
if not pending or redis.call('exists', KEYS[3]) == 1 then return 0 end
local record = cjson.decode(pending)
if redis.call('get', KEYS[2]) ~= record.run_id or record.status ~= ARGV[3] then return 0 end
record.status = ARGV[1]
record.response = cjson.decode(ARGV[2])
redis.call('set', KEYS[1], cjson.encode(record), 'KEEPTTL')
return 1
"""


def _key(conversation_id: str, request_id: str) -> str:
    """
    构建包含作用域的缓存键

    :param conversation_id: 对话 ID
    :param request_id: 请求 ID
    :return:
    """
    return f'{shared_chat_run_store.key_prefix}:{conversation_id}:input:{request_id}'


def _index_key(conversation_id: str) -> str:
    """
    构建对话输入请求的索引键

    :param conversation_id: 对话 ID
    :return:
    """
    return _key(conversation_id, 'pending')


def public_request(record: dict[str, Any]) -> dict[str, Any]:
    """
    只序列化公开字段，排除答案和加密密钥

    :param record: 输入请求记录
    :return:
    """
    return {key: value for key, value in record.items() if key not in {'run_id', 'response'}}


def validate_answers(questions: list[AIBuddyInputQuestion], answers: dict[str, str | list[str]]) -> None:
    """
    检查题目类型、必填和选项归属

    :param questions: 问题列表
    :param answers: 回答列表
    :return:
    """
    if set(answers) - {item.id for item in questions}:
        raise errors.RequestError(msg='回复包含未知问题')
    for question in questions:
        answer = answers.get(question.id)
        empty = not answer or (isinstance(answer, str) and not answer.strip())
        if question.required and empty:
            raise errors.RequestError(msg=f'请回答：{question.prompt}')
        if empty:
            continue
        if question.kind == AIBuddyInputQuestionKind.multiple:
            if not isinstance(answer, list) or len(set(answer)) != len(answer):
                raise errors.RequestError(msg='多选题答案无效')
            values = answer
        else:
            if not isinstance(answer, str) or len(answer) > 20000:
                raise errors.RequestError(msg='问题答案无效')
            values = [answer]
        if question.kind != AIBuddyInputQuestionKind.text and any(
            value not in {item.id for item in question.options} for value in values
        ):
            raise errors.RequestError(msg='回复包含无效选项')


def _secret_cipher() -> Fernet:
    """根据应用密钥构建敏感输入加密器"""
    key = hashlib.sha256(('ai-buddy-input:' + settings.TOKEN_SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


async def resolve_input_request(*, conversation_id: str, request_id: str, obj: ResolveAIBuddyInputRequestParam) -> None:
    """
    校验问题后原子提交，只接受当前运行中的一次回复

    :param conversation_id: 对话 ID
    :param request_id: 请求 ID
    :param obj: 输入请求答复参数
    :return:
    """
    client = shared_chat_run_store.client
    key = _key(conversation_id, request_id)
    raw = await client.get(key)
    if not raw:
        raise errors.ConflictError(msg='输入请求已结束')
    record = json.loads(raw)
    if record.get('status') != AIBuddyInputRequestStatus.pending:
        raise errors.ConflictError(msg='输入请求已处理或生成任务已结束')
    response: dict[str, Any] = {}
    if not obj.cancelled:
        if record['kind'] == AIBuddyInputRequestKind.secret:
            value = obj.secret.get_secret_value() if obj.secret else ''
            if not value or len(value) > 16000 or obj.answers is not None:
                raise errors.RequestError(msg='请输入当前请求所需的密钥')
            response['encrypted_secret'] = _secret_cipher().encrypt(value.encode()).decode()
        else:
            if obj.secret is not None:
                raise errors.RequestError(msg='普通问题不接受密钥')
            answers = obj.answers or {}
            validate_answers([AIBuddyInputQuestion.model_validate(item) for item in record['questions']], answers)
            response['answers'] = answers
    accepted = await client.eval(
        _RESOLVE_INPUT,
        3,
        key,
        shared_chat_run_store._key(conversation_id, 'owner'),
        shared_chat_run_store._key(conversation_id, 'cancel'),
        AIBuddyInputRequestStatus.cancelled if obj.cancelled else AIBuddyInputRequestStatus.answered,
        json.dumps(response, ensure_ascii=False),
        AIBuddyInputRequestStatus.pending,
    )
    if not accepted:
        raise errors.ConflictError(msg='输入请求已处理或生成任务已结束')


async def list_input_requests(*, conversation_id: str) -> list[dict[str, Any]]:
    """
    恢复当前运行中尚未答复的问题，不泄露密钥或答案

    :param conversation_id: 对话 ID
    :return:
    """
    client = shared_chat_run_store.client
    owner = await client.get(shared_chat_run_store._key(conversation_id, 'owner'))
    if not owner or await client.exists(shared_chat_run_store._key(conversation_id, 'cancel')):
        return []
    result = []
    for raw_id in await client.smembers(_index_key(conversation_id)):
        request_id = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
        raw = await client.get(_key(conversation_id, request_id))
        if not raw:
            continue
        record = json.loads(raw)
        if record.get('run_id') == owner and record.get('status') == AIBuddyInputRequestStatus.pending:
            result.append(public_request(record))
    return sorted(result, key=itemgetter('expires_at'))


async def wait_for_input(
    *,
    conversation_id: str,
    title: str,
    questions: list[AIBuddyInputQuestion],
    emit: Callable[[dict[str, Any]], Awaitable[None]],
    tool_call_id: str | None = None,
    secret: dict[str, str] | None = None,
) -> dict[str, Any] | SecretStr | None:
    """
    等待同一运行的真实输入，密钥仅交给受信调用者一次

    :param conversation_id: 对话 ID
    :param title: 标题
    :param questions: 问题列表
    :param emit: 事件回调
    :param tool_call_id: 工具调用 ID
    :param secret: 是否包含敏感内容
    :return:
    """
    if not secret and (not questions or len(questions) > 10 or len({item.id for item in questions}) != len(questions)):
        raise errors.RequestError(msg='问题数量或 ID 无效')
    client = shared_chat_run_store.client
    run_id = await client.get(shared_chat_run_store._key(conversation_id, 'owner'))
    if not run_id:
        raise errors.ConflictError(msg='当前对话没有运行中的任务')
    request_id = uuid4().hex
    key = _key(conversation_id, request_id)
    record = {
        'request_id': request_id,
        'run_id': run_id,
        'kind': AIBuddyInputRequestKind.secret if secret else AIBuddyInputRequestKind.questions,
        'status': AIBuddyInputRequestStatus.pending,
        'title': title[:2000],
        'questions': [item.model_dump() for item in questions],
        'tool_call_id': tool_call_id,
        'expires_at': int(time.time()) + _INPUT_TTL,
        **({'secret': secret} if secret else {}),
    }
    await client.set(key, json.dumps(record, ensure_ascii=False), ex=_INPUT_TTL)
    await client.sadd(_index_key(conversation_id), request_id)
    await client.expire(_index_key(conversation_id), _INPUT_TTL)
    try:
        await emit(public_request(record))
        while True:
            if await client.get(shared_chat_run_store._key(conversation_id, 'owner')) != run_id or await client.exists(
                shared_chat_run_store._key(conversation_id, 'cancel')
            ):
                await emit({**public_request(record), 'status': AIBuddyInputRequestStatus.cancelled})
                return None
            raw = await client.get(key)
            if not raw:
                await emit({**public_request(record), 'status': AIBuddyInputRequestStatus.cancelled})
                return None
            current = json.loads(raw)
            if current['status'] != AIBuddyInputRequestStatus.pending:
                await client.delete(key)
                await emit(public_request(current))
                if current['status'] == AIBuddyInputRequestStatus.cancelled:
                    return None
                if secret:
                    ciphertext = current['response']['encrypted_secret']
                    return SecretStr(_secret_cipher().decrypt(ciphertext.encode(), ttl=_INPUT_TTL).decode())
                return current['response']['answers']
            await asyncio.sleep(0.1)
    finally:
        await client.delete(key)
        await client.srem(_index_key(conversation_id), request_id)
