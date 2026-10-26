from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, NamedTuple, cast

from ag_ui.core import (
    ActivityMessage,
    AssistantMessage,
    DeveloperMessage,
    Message,
    ReasoningMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from pydantic_ai import ModelMessage, ModelRequest, ModelResponse
from pydantic_ai.messages import TextPart
from pydantic_ai.ui.ag_ui import AGUIAdapter

from backend.plugin.ai_buddy.enums import AIBuddyAgentMode, AIBuddyChatMessageType
from backend.plugin.ai_buddy.schema.chat_base import AIBuddyChatMessageUsageDetail
from backend.plugin.ai_buddy.schema.chat_message import (
    AIBuddyChatAgUiActivityMessageDetail,
    AIBuddyChatAgUiAssistantMessageDetail,
    AIBuddyChatAgUiDeveloperMessageDetail,
    AIBuddyChatAgUiMessagesSnapshotDetail,
    AIBuddyChatAgUiReasoningMessageDetail,
    AIBuddyChatAgUiSnapshotMessageDetail,
    AIBuddyChatAgUiSystemMessageDetail,
    AIBuddyChatAgUiToolMessageDetail,
    AIBuddyChatAgUiUserMessageDetail,
)
from backend.plugin.ai_buddy.security.output_redaction import redact_model_response
from backend.plugin.ai_buddy.utils.citation import text_part_citations

type SnapshotMessage = (
    AIBuddyChatAgUiUserMessageDetail
    | AIBuddyChatAgUiDeveloperMessageDetail
    | AIBuddyChatAgUiAssistantMessageDetail
    | AIBuddyChatAgUiSystemMessageDetail
    | AIBuddyChatAgUiToolMessageDetail
    | AIBuddyChatAgUiActivityMessageDetail
    | AIBuddyChatAgUiReasoningMessageDetail
)
type SnapshotMetaValue = datetime | str | int | dict[str, Any] | None


class SnapshotMessageBuildConfig(NamedTuple):
    """快照消息构建配置"""

    message_type: type[Message]
    fragment_type: str
    detail_model: type[Any]
    extra_fields_getter: Callable[[Any], dict[str, Any]]
    primary_without_suffix: bool = False


_SNAPSHOT_MESSAGE_BUILD_CONFIGS: tuple[SnapshotMessageBuildConfig, ...] = (
    SnapshotMessageBuildConfig(
        UserMessage,
        'user',
        AIBuddyChatAgUiUserMessageDetail,
        lambda message: {'content': message.content},
    ),
    SnapshotMessageBuildConfig(
        DeveloperMessage,
        'developer',
        AIBuddyChatAgUiDeveloperMessageDetail,
        lambda message: {'content': message.content},
    ),
    SnapshotMessageBuildConfig(
        SystemMessage,
        'system',
        AIBuddyChatAgUiSystemMessageDetail,
        lambda message: {'content': message.content},
    ),
    SnapshotMessageBuildConfig(
        AssistantMessage,
        'assistant',
        AIBuddyChatAgUiAssistantMessageDetail,
        lambda message: {
            'content': message.content,
            'tool_calls': message.tool_calls,
            'encrypted_value': message.encrypted_value,
        },
        primary_without_suffix=True,
    ),
    SnapshotMessageBuildConfig(
        ReasoningMessage,
        'reasoning',
        AIBuddyChatAgUiReasoningMessageDetail,
        lambda message: {
            'content': message.content,
            'encrypted_value': message.encrypted_value,
        },
    ),
    SnapshotMessageBuildConfig(
        ToolMessage,
        'tool',
        AIBuddyChatAgUiToolMessageDetail,
        lambda message: {
            'content': message.content,
            'tool_call_id': message.tool_call_id,
            'error': getattr(message, 'error', None),
            # 透传 outcome 等非 success 状态（pydantic-ai 编码于 encrypted_value）
            'encrypted_value': message.encrypted_value,
        },
    ),
    SnapshotMessageBuildConfig(
        ActivityMessage,
        'activity',
        AIBuddyChatAgUiActivityMessageDetail,
        lambda message: {
            'activity_type': message.activity_type,
            'content': cast('dict[str, Any]', message.content),
        },
    ),
)


def _build_snapshot_messages_from_encoded_messages(
    *,
    encoded_messages: Sequence[Message],
    base_meta: dict[str, SnapshotMetaValue],
    message_id: int | None,
    message_index: int,
    message_offset: int = 0,
    fallback_empty_assistant: bool = False,
) -> list[SnapshotMessage]:
    """
    根据标准 AG-UI 消息构建快照消息

    :param encoded_messages: 标准 AG-UI 消息列表
    :param base_meta: 公共元信息
    :param message_id: 持久化消息 ID
    :param message_index: 消息索引
    :param message_offset: 同一持久化消息内的模型消息序号
    :param fallback_empty_assistant: 是否在空结果时补一条空助手消息
    :return:
    """
    snapshot_messages: list[SnapshotMessage] = []
    fragment_indexes: defaultdict[str, int] = defaultdict(int)
    base_id = f'msg_{message_id if message_id is not None else message_index}'
    if message_offset:
        base_id = f'{base_id}_{message_offset}'

    for encoded_message in encoded_messages:
        for config in _SNAPSHOT_MESSAGE_BUILD_CONFIGS:
            if not isinstance(encoded_message, config.message_type):
                continue
            fragment_index = fragment_indexes[config.fragment_type]
            primary_without_suffix = not snapshot_messages and config.primary_without_suffix and fragment_index == 0
            snapshot_id = base_id if primary_without_suffix else f'{base_id}_{config.fragment_type}_{fragment_index}'
            snapshot_messages.append(
                cast(
                    'SnapshotMessage',
                    config.detail_model(
                        id=snapshot_id,
                        **config.extra_fields_getter(encoded_message),
                        **base_meta,
                    ),
                )
            )
            fragment_indexes[config.fragment_type] += 1
            break
        else:
            raise ValueError(f'不支持的 AG-UI 消息类型: {type(encoded_message).__name__}')

    if snapshot_messages or not fallback_empty_assistant:
        return snapshot_messages
    return [
        AIBuddyChatAgUiAssistantMessageDetail(
            id=base_id,
            content=None,
            tool_calls=None,
            **base_meta,
        )
    ]


def _serialize_request_message(
    *,
    message: ModelRequest,
    conversation_id: str | None,
    message_id: int | None,
    provider_id: int | None,
    model_id: str | None,
    message_index: int,
    turn_context: dict[str, Any] | None = None,
    message_offset: int = 0,
) -> list[SnapshotMessage]:
    """
    序列化请求消息

    :param message: 请求消息
    :param conversation_id: 对话 ID
    :param message_id: 持久化消息 ID
    :param provider_id: 供应商 ID
    :param model_id: 模型 ID
    :param message_index: 消息索引
    :param turn_context: 本轮实际组合
    :param message_offset: 同一持久化消息内的模型消息序号
    :return:
    """
    if not message.parts:
        return []

    base_meta = {
        'conversation_id': conversation_id,
        'persisted_message_id': message_id,
        'provider_id': provider_id,
        'model_id': model_id,
        'created_time': message.parts[0].timestamp,
        'message_index': message_index,
        'message_type': (
            AIBuddyChatMessageType(message.state) if message.state != 'complete' else AIBuddyChatMessageType.normal
        ),
        'turn_context': turn_context,
    }
    encoded_messages = AGUIAdapter.dump_messages([message], preserve_file_data=True)
    return _build_snapshot_messages_from_encoded_messages(
        encoded_messages=encoded_messages,
        base_meta=base_meta,
        message_id=message_id,
        message_index=message_index,
        message_offset=message_offset,
    )


def _serialize_response_message(
    *,
    message: ModelResponse,
    conversation_id: str | None,
    message_id: int | None,
    provider_id: int | None,
    model_id: str | None,
    message_index: int,
    turn_context: dict[str, Any] | None = None,
    message_offset: int = 0,
) -> list[SnapshotMessage]:
    """
    序列化响应消息

    :param message: 响应消息
    :param conversation_id: 对话 ID
    :param message_id: 持久化消息 ID
    :param provider_id: 供应商 ID
    :param model_id: 模型 ID
    :param message_index: 消息索引
    :param turn_context: 本轮实际组合
    :param message_offset: 同一持久化消息内的模型消息序号
    :return:
    """
    base_meta = {
        'conversation_id': conversation_id,
        'persisted_message_id': message_id,
        'provider_id': provider_id,
        'model_id': model_id or message.model_name,
        'created_time': message.timestamp,
        'message_index': message_index,
        'turn_context': turn_context,
        # 对齐 pydantic-ai ModelResponse.state（complete/incomplete/suspended/interrupted）
        'message_type': (
            AIBuddyChatMessageType.error
            if (message.metadata or {}).get('is_error')
            else AIBuddyChatMessageType.normal
            if message.state == 'complete'
            else AIBuddyChatMessageType(message.state)
        ),
    }
    display_message = (
        message
        if (turn_context or {}).get('agent_mode') == AIBuddyAgentMode.coding
        else redact_model_response(message, preserve_signed_thinking=False)
    )
    encoded_messages = AGUIAdapter.dump_messages([display_message], preserve_file_data=True)
    snapshot_messages = _build_snapshot_messages_from_encoded_messages(
        encoded_messages=encoded_messages,
        base_meta=base_meta,
        message_id=message_id,
        message_index=message_index,
        message_offset=message_offset,
        fallback_empty_assistant=True,
    )
    sources = text_part_citations([part for part in message.parts if isinstance(part, TextPart)])
    if sources:
        for snapshot in reversed(snapshot_messages):
            if isinstance(snapshot, AIBuddyChatAgUiAssistantMessageDetail):
                snapshot.sources = sources
                break
    usage = message.usage
    input_tokens = usage.input_tokens or 0
    output_tokens = usage.output_tokens or 0
    cache_read_tokens = usage.cache_read_tokens or 0
    cache_write_tokens = usage.cache_write_tokens or 0
    input_audio_tokens = usage.input_audio_tokens or 0
    output_audio_tokens = usage.output_audio_tokens or 0
    cache_audio_read_tokens = usage.cache_audio_read_tokens or 0
    details = dict(usage.details or {})
    cost = None
    raw_cost = getattr(usage, 'cost', None)
    if raw_cost is not None:
        cost = float(raw_cost)
    elif message.model_name:
        try:
            cost = float(message.cost().total_price)
        except Exception:
            pass
    if (
        input_tokens == 0
        and output_tokens == 0
        and cache_read_tokens == 0
        and cache_write_tokens == 0
        and input_audio_tokens == 0
        and output_audio_tokens == 0
        and cache_audio_read_tokens == 0
        and not details
        and cost is None
    ):
        return snapshot_messages
    usage = AIBuddyChatMessageUsageDetail(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        input_audio_tokens=input_audio_tokens,
        output_audio_tokens=output_audio_tokens,
        cache_audio_read_tokens=cache_audio_read_tokens,
        details=details,
        cost=cost,
    )

    attached = False
    result: list[SnapshotMessage] = []
    for item in snapshot_messages:
        if not attached and isinstance(item, AIBuddyChatAgUiAssistantMessageDetail):
            result.append(item.model_copy(update={'usage': usage}))
            attached = True
        else:
            result.append(item)
    return result


def serialize_messages_to_snapshot(
    messages: Sequence[ModelMessage],
    *,
    conversation_id: str | None = None,
    message_ids: Sequence[int | None] | None = None,
    provider_ids: Sequence[int | None] | None = None,
    model_ids: Sequence[str | None] | None = None,
    message_indexes: Sequence[int | None] | None = None,
    turn_contexts: Sequence[dict[str, Any] | None] | None = None,
    errors: Mapping[int, tuple[str, dict[str, Any] | None]] | None = None,
    error_fallbacks: Sequence[dict[str, Any]] | None = None,
) -> AIBuddyChatAgUiMessagesSnapshotDetail:
    """
    序列化模型消息为快照

    :param messages: 模型消息列表
    :param conversation_id: 对话 ID
    :param message_ids: 持久化消息 ID 列表
    :param provider_ids: 供应商 ID 列表
    :param model_ids: 模型 ID 列表
    :param message_indexes: 持久化消息索引列表
    :param turn_contexts: 本轮实际组合列表
    :param errors: 消息 ID 到错误正文和详情
    :param error_fallbacks: 无模型正文的失败消息元信息
    :return:
    """
    snapshot_messages: list[AIBuddyChatAgUiSnapshotMessageDetail] = []
    row_offsets: defaultdict[int, int] = defaultdict(int)
    message_contexts = zip(
        messages,
        message_ids or [None] * len(messages),
        provider_ids or [None] * len(messages),
        model_ids or [None] * len(messages),
        message_indexes or [None] * len(messages),
        turn_contexts or [None] * len(messages),
        strict=False,
    )
    for fallback_index, (
        message,
        message_id,
        provider_id,
        model_id,
        message_index,
        turn_context,
    ) in enumerate(message_contexts):
        resolved_message_index = fallback_index if message_index is None else message_index
        row_key = message_id if message_id is not None else resolved_message_index
        message_offset = row_offsets[row_key]
        row_offsets[row_key] += 1
        if isinstance(message, ModelRequest):
            request_messages = _serialize_request_message(
                message=message,
                conversation_id=conversation_id,
                message_id=message_id,
                provider_id=provider_id,
                model_id=model_id,
                message_index=resolved_message_index,
                turn_context=turn_context,
                message_offset=message_offset,
            )
            snapshot_messages.extend(request_messages)
            continue
        if isinstance(message, ModelResponse):
            response_messages = _serialize_response_message(
                message=message,
                conversation_id=conversation_id,
                message_id=message_id,
                provider_id=provider_id,
                model_id=model_id,
                message_index=resolved_message_index,
                turn_context=turn_context,
                message_offset=message_offset,
            )
            snapshot_messages.extend(response_messages)

    error_map = errors or {}
    if not error_map:
        return AIBuddyChatAgUiMessagesSnapshotDetail(messages=snapshot_messages)

    applied: set[int] = set()
    messages: list[AIBuddyChatAgUiSnapshotMessageDetail] = []
    for message in snapshot_messages:
        message_id = getattr(message, 'persisted_message_id', None)
        if (
            isinstance(message, AIBuddyChatAgUiAssistantMessageDetail)
            and isinstance(message_id, int)
            and message_id in error_map
        ):
            error_text, error_detail = error_map[message_id]
            updates: dict[str, Any] = {
                'message_type': AIBuddyChatMessageType.error,
                'error': error_text,
                'error_detail': error_detail,
            }
            if not message.content:
                updates['content'] = error_text
            message = message.model_copy(update=updates)
            applied.add(message_id)
        messages.append(message)
    for fallback in error_fallbacks or ():
        message_id = fallback.get('message_id')
        if not isinstance(message_id, int) or message_id in applied or message_id not in error_map:
            continue
        error_text, error_detail = error_map[message_id]
        messages.append(
            AIBuddyChatAgUiAssistantMessageDetail(
                id=f'msg_{message_id}',
                content=error_text,
                error=error_text,
                error_detail=error_detail,
                conversation_id=fallback.get('conversation_id', conversation_id),
                persisted_message_id=message_id,
                provider_id=fallback.get('provider_id'),
                model_id=fallback.get('model_id'),
                created_time=fallback.get('created_time'),
                message_index=fallback.get('message_index'),
                message_type=AIBuddyChatMessageType.error,
            )
        )

    return AIBuddyChatAgUiMessagesSnapshotDetail(messages=messages)
