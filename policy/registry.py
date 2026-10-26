from sqlalchemy.ext.asyncio import AsyncSession

from backend.plugin.ai_buddy.policy.base import AIBuddyResourcePolicy
from backend.plugin.ai_buddy.policy.context import AIBuddyInvocationContext

_ai_buddy_resource_policies: list[AIBuddyResourcePolicy] = []


def register_ai_buddy_resource_policy(policy: AIBuddyResourcePolicy) -> None:
    """
    注册 AI 资源与调用策略

    :param policy: AI 资源与调用策略
    :return:
    """
    if policy not in _ai_buddy_resource_policies:
        _ai_buddy_resource_policies.append(policy)


async def validate_ai_buddy_invocation(*, db: AsyncSession, context: AIBuddyInvocationContext) -> None:
    """
    校验 AI 调用策略

    按注册顺序串行执行，任一策略拒绝即中断

    :param db: 数据库会话
    :param context: AI 调用策略上下文
    :return:
    """
    # 同一个 AsyncSession 不能被并发操作，策略必须按注册顺序串行执行
    for policy in tuple(_ai_buddy_resource_policies):
        await policy.before_invoke(db=db, context=context)
