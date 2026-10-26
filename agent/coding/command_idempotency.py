import hashlib
import json
import re

from backend.common.exception import errors
from backend.plugin.ai_buddy.agent.coding.types import AgentRunContext
from backend.plugin.ai_buddy.agent.work.run_store import shared_chat_run_store
from backend.plugin.ai_buddy.schema.command import AIBuddyCommandResult

_KEY_PATTERN = re.compile(r'^[A-Za-z0-9_.:-]{8,128}$')
_RUNNING_TTL_SECONDS = 600
_RESULT_TTL_SECONDS = 3600


async def run_idempotent_command(
    *, ctx: AgentRunContext, command: str, idempotency_key: str | None
) -> AIBuddyCommandResult:
    """
    按幂等键执行命令，同一键重试时返回首次结果而不重复产生副作用

    :param ctx: 运行上下文
    :param command: 已确认的命令
    :param idempotency_key: 幂等键，为空时直接执行
    :return:
    """
    if ctx.sandbox is None:
        raise errors.RequestError(msg='当前对话没有可用的执行环境')
    if idempotency_key is None:
        return await ctx.sandbox.run_command(command=command)
    if not _KEY_PATTERN.fullmatch(idempotency_key):
        raise errors.RequestError(msg='幂等键必须是 8 到 128 位字母、数字或 _.:-')
    digest = hashlib.sha256(command.encode()).hexdigest()
    redis_key = (
        f'{shared_chat_run_store.key_prefix}:command:{ctx.user_id}:{ctx.conversation_id}:'
        f'{hashlib.sha256(idempotency_key.encode()).hexdigest()}'
    )
    client = shared_chat_run_store.client
    claimed = await client.set(redis_key, json.dumps({'digest': digest}), nx=True, ex=_RUNNING_TTL_SECONDS)
    if not claimed:
        raw = await client.get(redis_key)
        record = json.loads(raw) if raw else {}
        if record.get('digest') != digest:
            raise errors.ConflictError(msg='幂等键已用于另一条命令')
        if 'result' not in record:
            raise errors.ConflictError(msg='相同幂等键的命令正在执行')
        return AIBuddyCommandResult.model_validate(record['result'])
    try:
        result = await ctx.sandbox.run_command(command=command)
    except BaseException:
        # 未取得执行结果时释放占位，允许调用方用同一键重试
        await client.delete(redis_key)
        raise
    await client.set(redis_key, json.dumps({'digest': digest, 'result': result.model_dump()}), ex=_RESULT_TTL_SECONDS)
    return result
