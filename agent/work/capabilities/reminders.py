from collections.abc import Sequence

from pydantic_ai_harness import WarnNearLimits
from pydantic_ai_harness.system_reminders import GoalReanchor, Reminder, SystemReminders
from pydantic_ai_harness.warn_on_cache_busts import WarnOnCacheBusts

from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType


def build_reminder_capabilities(ctx: CapabilityContext) -> Sequence[CapabilityResult]:
    """
    长运行中重申工作目标，并在接近窗口上限或 cache 被打穿时提醒

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return ()

    reminders: list[Reminder] = [
        Reminder('不要把当前产品当成代码代理：不要主动改仓库或跑 shell，除非用户明确要求。', interval=6, tag=None),
    ]
    if ctx.conversation_goal:
        reminders.append(Reminder(f'对话目标：{ctx.conversation_goal}', interval=4, tag=None))
    return (
        CapabilityResult(
            capability=SystemReminders(
                reminders=reminders,
                dynamic_reminders=[GoalReanchor()],
            )
        ),
        CapabilityResult(capability=WarnOnCacheBusts()),
        CapabilityResult(capability=WarnNearLimits(max_context_fraction=0.9, context_window=ctx.context_window)),
    )
