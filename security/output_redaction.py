from dataclasses import replace

from pydantic_ai.messages import ModelResponse, TextPart, ThinkingPart
from pydantic_ai_harness.guardrails.detectors import redact_secrets

from backend.plugin.ai_buddy.security.pii import compose_text_guard, redact_pii

_output_guard = compose_text_guard(redact_secrets, redact_pii)


def redact_output_text(text: str) -> str:
    """
    统一清洗将展示或持久化的模型文本

    :param text: 文本内容
    :return:
    """
    result = _output_guard(text)
    return result.replacement if result.action == 'replace' and isinstance(result.replacement, str) else text


def redact_model_response(message: ModelResponse, *, preserve_signed_thinking: bool = True) -> ModelResponse:
    """
    清洗响应副本，签名推理原文仅在供应商重放历史中保留

    :param message: 消息内容
    :param preserve_signed_thinking: 是否保留签名思考内容
    :return:
    """
    return replace(
        message,
        parts=[
            replace(part, content=redact_output_text(part.content))
            if isinstance(part, TextPart)
            or (isinstance(part, ThinkingPart) and not (preserve_signed_thinking and part.signature))
            else part
            for part in message.parts
        ],
    )
