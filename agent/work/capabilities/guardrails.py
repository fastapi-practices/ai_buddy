from collections.abc import AsyncIterable, Sequence
from dataclasses import replace

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    AgentStreamEvent,
    ModelResponse,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    ThinkingPart,
)
from pydantic_ai.models import ModelRequestContext
from pydantic_ai_harness.guardrails import InputGuardrail, OutputGuardrail, ToolGuardrail
from pydantic_ai_harness.guardrails.detectors import for_text, for_tool_result_text, redact_secrets

from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import AIBuddyChatGenerationType
from backend.plugin.ai_buddy.security.jev import jev_enabled, jev_input_ok, jev_tool_decide_for_run
from backend.plugin.ai_buddy.security.output_redaction import redact_model_response, redact_output_text
from backend.plugin.ai_buddy.security.pii import compose_text_guard, redact_pii


class RedactModelText(AbstractCapability[ChatAgentDeps]):
    """先清洗完整文本分段，再向客户端发布，并清洗模型历史"""

    id = 'redact-model-text'

    async def after_model_request(
        self,
        ctx: RunContext[ChatAgentDeps],
        *,
        request_context: ModelRequestContext,
        response: ModelResponse,
    ) -> ModelResponse:
        """
        在响应写入历史前清洗文本

        :param ctx: 运行上下文
        :param request_context: 请求上下文
        :param response: 模型响应
        :return:
        """
        return redact_model_response(response)

    async def wrap_run_event_stream(
        self, ctx: RunContext[ChatAgentDeps], *, stream: AsyncIterable[AgentStreamEvent]
    ) -> AsyncIterable[AgentStreamEvent]:
        """
        完整分段到达后才发布，防止敏感串跨 delta 绕过清洗

        :param ctx: 运行上下文
        :param stream: 事件流
        :return:
        """
        pending: dict[int, PartStartEvent] = {}
        try:
            async for event in stream:
                if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart | ThinkingPart):
                    pending[event.index] = event
                    continue
                if isinstance(event, PartDeltaEvent) and event.index in pending:
                    continue
                if isinstance(event, PartEndEvent) and event.index in pending:
                    start = pending.pop(event.index)
                    if isinstance(event.part, TextPart | ThinkingPart):
                        safe_part = replace(event.part, content=redact_output_text(event.part.content))
                        yield replace(start, part=safe_part)
                        yield replace(event, part=safe_part)
                    continue
                yield event
        finally:
            if close := getattr(stream, 'aclose', None):
                await close()


def build_guardrail_capabilities(ctx: CapabilityContext) -> Sequence[CapabilityResult]:
    """
    脱敏密钥，并用 Jev 判定输入与工具调用

    :param ctx: 能力构建上下文
    :return:
    """
    if ctx.forwarded_props.generation_type != AIBuddyChatGenerationType.text:
        return ()
    guard = compose_text_guard(redact_secrets, redact_pii)
    input_guards = [guard]
    if jev_enabled():
        input_guards.append(jev_input_ok)
    return (
        CapabilityResult(capability=InputGuardrail(guard=input_guards)),
        CapabilityResult(capability=RedactModelText()),
        CapabilityResult(capability=OutputGuardrail(guard=for_text(guard, on_other='allow'))),
        CapabilityResult(
            capability=ToolGuardrail(
                guard=jev_tool_decide_for_run if jev_enabled() else None,
                result_guard=for_tool_result_text(guard, on_other='allow'),
            )
        ),
    )
