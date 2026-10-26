import asyncio

from collections.abc import Sequence
from typing import Any, Literal

from pydantic_ai import ModelMessage, ModelMessagesTypeAdapter, ModelRequest, ModelResponse, TextPart, UserPromptPart

from backend.common.exception import errors
from backend.plugin.ai_buddy.dataclasses import ChatConversationState
from backend.plugin.ai_buddy.enums import AIBuddyMessageRole
from backend.plugin.ai_buddy.model import AIBuddyMessage
from backend.plugin.ai_buddy.utils.media_store import decode_model_message_payloads

type ChatMessageRole = Literal[AIBuddyMessageRole.assistant, AIBuddyMessageRole.user]
type StoredModelMessage = ModelRequest | ModelResponse
_PREVIEW_MAX_CHARS = 256


def _user_prompt_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ''
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict):
            text = item.get('text') or item.get('content')
            if isinstance(text, str) and text:
                parts.append(text)
            continue
        text = getattr(item, 'text', None) or getattr(item, 'content', None)
        if isinstance(text, str) and text:
            parts.append(text)
    return '\n'.join(parts)


def extract_payload_preview_text(payloads: Sequence[dict[str, Any]]) -> str:
    """
    从原始消息 JSON 取预览文本，不还原附件二进制

    :param payloads: 模型消息 JSON 列表
    :return:
    """
    for payload in reversed(list(payloads)):
        parts = payload.get('parts')
        if not isinstance(parts, list):
            continue
        texts: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            content = part.get('content')
            if isinstance(content, str) and content.strip():
                texts.append(content)
            elif isinstance(content, list):
                text = _user_prompt_text(content)
                if text:
                    texts.append(text)
        if texts:
            return '\n'.join(texts)
    return ''


def extract_message_preview_text(*, message: StoredModelMessage) -> str:
    """
    从模型消息取出列表预览文本

    :param message: 模型消息
    :return:
    """
    if isinstance(message, ModelRequest):
        for part in message.parts:
            if isinstance(part, UserPromptPart):
                return _user_prompt_text(part.content)
        return ''
    if isinstance(message, ModelResponse):
        return '\n'.join(part.content for part in message.parts if isinstance(part, TextPart) and part.content)
    return ''


def normalize_message_preview(*, text: str) -> str | None:
    """
    标准化消息预览

    :param text: 原始预览文本
    :return:
    """
    normalized = ' '.join(text.split())
    if not normalized:
        return None
    return normalized[:_PREVIEW_MAX_CHARS]


def is_user_prompt_message(*, message: StoredModelMessage) -> bool:
    """
    判断是否为用户输入消息

    :param message: 模型消息
    :return:
    """
    return isinstance(message, ModelRequest) and bool(message.parts) and isinstance(message.parts[0], UserPromptPart)


def filter_history_model_messages(messages: Sequence[StoredModelMessage]) -> list[StoredModelMessage]:
    """
    下一轮发给模型的历史不带上空响应，避免把失败占位塞进上下文

    :param messages: 展开后的模型消息
    :return:
    """
    return [message for message in messages if not (isinstance(message, ModelResponse) and not message.parts)]


def build_chat_message_record(
    *,
    role: ChatMessageRole,
    model_messages: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """
    构建聊天消息记录字段

    :param role: 聊天消息角色
    :param model_messages: 原始 Pydantic 模型消息
    :return:
    """
    return {
        'role': role,
        'model_messages': list(model_messages),
    }


def get_message_row_model_message_payloads(row: AIBuddyMessage) -> list[dict[str, Any]]:
    """
    获取消息行中的原始模型消息列表

    :param row: 消息行
    :return:
    """
    return row.model_messages or []


async def expand_message_rows(
    message_rows: Sequence[AIBuddyMessage],
) -> tuple[list[StoredModelMessage], list[tuple[int, int]]]:
    """
    展开消息行中的原始模型消息

    :param message_rows: 消息行
    :return:
    """
    raw_messages: list[dict[str, Any]] = []
    row_message_ranges: list[tuple[int, int]] = []
    for row in message_rows:
        start = len(raw_messages)
        row_messages = get_message_row_model_message_payloads(row)
        raw_messages.extend(row_messages)
        row_message_ranges.append((start, len(raw_messages)))
    if not raw_messages:
        return [], row_message_ranges
    restored = await decode_model_message_payloads(raw_messages)
    validated = await asyncio.to_thread(ModelMessagesTypeAdapter.validate_python, restored)
    return list(validated), row_message_ranges


def expand_message_row_metadata(
    message_rows: Sequence[AIBuddyMessage],
    row_message_ranges: Sequence[tuple[int, int]],
) -> tuple[
    list[int | None],
    list[int | None],
    list[str | None],
    list[int | None],
    list[dict[str, Any] | None],
]:
    """
    展开消息行元信息到模型消息粒度

    :param message_rows: 消息行
    :param row_message_ranges: 行到模型消息范围映射
    :return:
    """
    message_ids: list[int | None] = []
    provider_ids: list[int | None] = []
    model_ids: list[str | None] = []
    message_indexes: list[int | None] = []
    turn_contexts: list[dict[str, Any] | None] = []
    for row, (start, end) in zip(message_rows, row_message_ranges, strict=False):
        count = end - start
        message_ids.extend([row.id] * count)
        provider_ids.extend([row.provider_id] * count)
        model_ids.extend([row.model_id] * count)
        message_indexes.extend([row.message_index] * count)
        turn_contexts.extend([row.turn_context] * count)
    return message_ids, provider_ids, model_ids, message_indexes, turn_contexts


def get_row_model_messages(
    *,
    model_messages: Sequence[StoredModelMessage],
    row_message_ranges: Sequence[tuple[int, int]],
    row_index: int,
) -> list[StoredModelMessage]:
    """
    获取指定消息行对应的原始模型消息

    :param model_messages: 展开后的模型消息
    :param row_message_ranges: 行到模型消息范围映射
    :param row_index: 行索引
    :return:
    """
    start, end = row_message_ranges[row_index]
    return list(model_messages[start:end])


def parse_current_turn_input(*, messages: list[ModelMessage]) -> tuple[list[ModelMessage], str, bool]:
    """
    提取当前轮用户消息并解析文本和附件状态

    :param messages: 解码或清理后的模型消息
    :return:
    """
    for message in reversed(messages):
        if not is_user_prompt_message(message=message):
            continue
        first_part = message.parts[0]
        assert isinstance(first_part, UserPromptPart)
        content_items = [first_part.content] if isinstance(first_part.content, str) else list(first_part.content)
        prompt_parts = [item for item in content_items if isinstance(item, str)]
        has_binary_input = len(prompt_parts) != len(content_items)
        prompt = ' '.join(' '.join(part.split()) for part in prompt_parts if part.split())
        return [message], prompt, has_binary_input
    raise errors.RequestError(msg='最后一条消息必须是用户消息')


def is_user_message_row(
    *,
    model_messages: list[ModelRequest | ModelResponse],
    row_index: int,
    row_model_message_ranges: list[tuple[int, int]],
) -> bool:
    """
    判断是否为用户消息行

    :param model_messages: 模型消息列表
    :param row_index: 消息行索引
    :param row_model_message_ranges: 行到模型消息范围映射
    :return:
    """
    row_messages = get_row_model_messages(
        model_messages=model_messages,
        row_message_ranges=row_model_message_ranges,
        row_index=row_index,
    )
    return len(row_messages) == 1 and is_user_prompt_message(message=row_messages[0])


def get_message_row_index(*, message_rows: list[AIBuddyMessage], pk: int) -> int:
    """
    获取消息行索引

    :param message_rows: 消息行列表
    :param pk: 消息主键
    :return:
    """
    message_row_index = next((index for index, row in enumerate(message_rows) if row.id == pk), None)
    if message_row_index is None:
        raise errors.NotFoundError(msg='消息不存在，请刷新后重试')
    return message_row_index


def get_regenerate_target(*, state: ChatConversationState, pk: int) -> tuple[int, int]:
    """
    获取可重发的用户消息行及其模型消息结束下标

    :param state: 对话状态
    :param pk: 消息主键
    :return:
    """
    target_index = get_message_row_index(message_rows=state.message_rows, pk=pk)
    target_messages = get_row_model_messages(
        model_messages=state.model_messages,
        row_message_ranges=state.row_model_message_ranges,
        row_index=target_index,
    )
    if len(target_messages) != 1 or not is_user_prompt_message(message=target_messages[0]):
        raise errors.RequestError(msg='仅支持根据用户消息重发')
    last_user_index: int | None = None
    for index in range(len(state.message_rows)):
        if is_user_message_row(
            model_messages=state.model_messages,
            row_index=index,
            row_model_message_ranges=state.row_model_message_ranges,
        ):
            last_user_index = index
    if last_user_index is None:
        raise errors.RequestError(msg='当前对话没有可重发的用户消息')
    if target_index != last_user_index:
        raise errors.RequestError(msg='仅支持重发最后一条用户消息，请刷新后重试')
    _, target_end_index = state.row_model_message_ranges[target_index]
    return target_index, target_end_index
