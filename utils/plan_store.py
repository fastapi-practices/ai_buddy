from pydantic_ai_harness.planning import RedisPlanStore

from backend.common.log import log
from backend.core.conf import settings
from backend.database.redis import redis_client

_PLAN_IDLE_EXPIRE_SECONDS = 7 * 24 * 60 * 60


def _plan_redis_prefix() -> str:
    """对话规划 Redis 前缀"""
    return f'{settings.PLUGIN_REDIS_PREFIX}:ai_buddy:plan'


def _build_plan_redis_key(*, user_id: int, conversation_id: str) -> str:
    """
    构建对话规划的 Redis 键

    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :return:
    """
    return f'{_plan_redis_prefix()}:{{{user_id}:{conversation_id}}}'


def get_plan_store(*, user_id: int, conversation_id: str) -> RedisPlanStore:
    """
    获取对话规划存储

    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :return:
    """
    return RedisPlanStore(
        redis_client,
        session=f'{user_id}:{conversation_id}',
        key_prefix=_plan_redis_prefix(),
        expire_seconds=_PLAN_IDLE_EXPIRE_SECONDS,
    )


async def copy_conversation_plan(*, user_id: int, source_conversation_id: str, target_conversation_id: str) -> None:
    """
    复刻对话对应的规划

    :param user_id: 用户 ID
    :param source_conversation_id: 源对话 ID
    :param target_conversation_id: 目标对话 ID
    :return:
    """
    try:
        payload = await redis_client.get(_build_plan_redis_key(user_id=user_id, conversation_id=source_conversation_id))
        if not payload:
            return
        await redis_client.set(
            _build_plan_redis_key(user_id=user_id, conversation_id=target_conversation_id),
            payload,
            ex=_PLAN_IDLE_EXPIRE_SECONDS,
        )
    except Exception as exc:
        log.warning(f'复刻对话规划失败 conversation_id={source_conversation_id}: {exc}')


async def delete_conversation_plan(*, user_id: int, conversation_id: str) -> None:
    """
    删除对话对应的规划

    :param user_id: 用户 ID
    :param conversation_id: 对话 ID
    :return:
    """
    try:
        await redis_client.delete(_build_plan_redis_key(user_id=user_id, conversation_id=conversation_id))
    except Exception as exc:
        log.warning(f'删除对话规划失败 conversation_id={conversation_id}: {exc}')
