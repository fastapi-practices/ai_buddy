from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from pydantic_ai.capabilities import WrapModelRequestHandler
from pydantic_ai.messages import CachePoint, ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.tools import RunContext
from pydantic_ai_harness import WarnNearLimits
from pydantic_ai_harness._cache_points import has_cache_point_target
from pydantic_ai_harness.system_reminders import GoalReanchor, Reminder, ReminderFiredEvent, SystemReminders
from pydantic_ai_harness.warn_on_cache_busts import WarnOnCacheBusts

from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType


class _SystemReminders(SystemReminders):
    """在历史压缩后注入提醒，OpenAI 显式缓存模型不前置 CachePoint"""

    @staticmethod
    async def wrap_model_request(
        ctx: RunContext[Any],
        *,
        request_context: ModelRequestContext,
        handler: WrapModelRequestHandler,
    ) -> ModelResponse:
        """
        将提醒注入留给压缩后的 before_model_request

        :param ctx: 运行上下文
        :param request_context: 模型请求上下文
        :param handler: 下一层模型请求处理函数
        :return:
        """
        return await handler(request_context)

    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        """
        向当前请求追加提醒，不写入持久历史

        :param ctx: 运行上下文
        :param request_context: 模型请求上下文
        :return:
        """
        messages = request_context.messages
        if messages and isinstance(last := messages[-1], ModelRequest):
            self._request_count += 1
            fired = self._eligible_static(ctx)
            dynamic_texts = await self._collect_dynamic(ctx)
            texts = [text for _, text in fired] + dynamic_texts
            if texts:
                text = '\n\n'.join(texts)
                content: str | list[CachePoint | str] = text
                if not ctx.model.profile.get('openai_supports_prompt_cache_breakpoints', False):
                    content = [CachePoint(ttl=self.cache_ttl), text] if has_cache_point_target(last.parts) else [text]
                messages[-1] = replace(last, parts=[*last.parts, UserPromptPart(content=content)])
                for key, _text in fired:
                    self._fire_counts[key] = self._fire_counts.get(key, 0) + 1
                for reminder_text in texts:
                    await ctx.emit(ReminderFiredEvent(text=reminder_text))
                if self.on_fire is not None:
                    for reminder_text in texts:
                        self.on_fire(reminder_text)
        return request_context


def build_reminder_capabilities(ctx: CapabilityContext) -> Sequence[CapabilityResult]:
    """
    长运行中重申工作目标，并在接近窗口上限或 cache 被打穿时提醒

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return ()

    reminders: list[Reminder] = [
        Reminder('不要把当前产品当成代码代理：不要主动改仓库或跑 shell，除非用户明确要求。', interval=6),
    ]
    if ctx.conversation_goal:
        reminders.append(Reminder(f'对话目标：{ctx.conversation_goal}', interval=4))
    return (
        CapabilityResult(
            capability=_SystemReminders(
                reminders=reminders,
                dynamic_reminders=[GoalReanchor()],
            )
        ),
        CapabilityResult(capability=WarnOnCacheBusts()),
        CapabilityResult(capability=WarnNearLimits(max_context_fraction=0.9, context_window=ctx.context_window)),
    )
