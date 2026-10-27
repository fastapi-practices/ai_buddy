import codecs
import json

from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

from ag_ui.core import EventType
from starlette.responses import StreamingResponse

_THINKING_EVENTS = frozenset({
    EventType.THINKING_START,
    EventType.THINKING_END,
    EventType.THINKING_TEXT_MESSAGE_START,
    EventType.THINKING_TEXT_MESSAGE_CONTENT,
    EventType.THINKING_TEXT_MESSAGE_END,
    EventType.REASONING_START,
    EventType.REASONING_MESSAGE_START,
    EventType.REASONING_MESSAGE_CONTENT,
    EventType.REASONING_MESSAGE_END,
    EventType.REASONING_MESSAGE_CHUNK,
    EventType.REASONING_END,
    EventType.REASONING_ENCRYPTED_VALUE,
})
_TOOL_EVENTS = frozenset({
    EventType.TOOL_CALL_START,
    EventType.TOOL_CALL_ARGS,
    EventType.TOOL_CALL_END,
    EventType.TOOL_CALL_CHUNK,
    EventType.TOOL_CALL_RESULT,
})


def _parse_sse_payload(frame: str) -> dict[str, Any] | None:
    """
    提取 SSE 数据行中的 AG-UI 事件

    :param frame: SSE 数据帧
    :return:
    """
    data = '\n'.join(line[5:].lstrip() for line in frame.splitlines() if line.startswith('data:'))
    if not data:
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


async def _iter_sse_frames(chunks: AsyncIterator[str | bytes]) -> AsyncIterator[str]:
    """
    按 SSE 边界增量解码事件，并在消费结束时关闭源迭代器

    :param chunks: 数据块迭代器
    :return:
    """
    decoder = codecs.getincrementaldecoder('utf-8')()
    buffer = ''
    try:
        async for chunk in chunks:
            buffer += chunk if isinstance(chunk, str) else decoder.decode(bytes(chunk))
            buffer = buffer.replace('\r\n', '\n')
            while '\n\n' in buffer:
                frame, buffer = buffer.split('\n\n', 1)
                yield frame
        buffer += decoder.decode(b'', final=True)
        leftover = buffer.replace('\r\n', '\n').rstrip('\r\n')
        if leftover.strip():
            yield leftover
    finally:
        close = getattr(chunks, 'aclose', None)
        if close is not None:
            await close()


def _keep_channel_sse_frame(frame: str, *, show_thinking: bool, show_tool_hints: bool) -> bool:
    """
    判断 IM 出站是否保留该 AG-UI SSE 帧

    :param frame: 不含尾部分隔的 SSE 帧
    :param show_thinking: 是否展示思考过程
    :param show_tool_hints: 是否展示工具调用提示
    :return:
    """
    if show_thinking and show_tool_hints:
        return True
    payload = _parse_sse_payload(frame)
    if payload is None:
        return True
    try:
        event_type = EventType(payload.get('type'))
    except (TypeError, ValueError):
        return True
    thinking_hidden = not show_thinking and event_type in _THINKING_EVENTS
    tool_hidden = not show_tool_hints and event_type in _TOOL_EVENTS
    return not thinking_hidden and not tool_hidden


async def _iter_filtered_frames(
    chunks: AsyncIterator[str | bytes],
    *,
    show_thinking: bool,
    show_tool_hints: bool,
) -> AsyncIterator[str]:
    """
    生成过滤思考和工具提示后的流式文本帧

    :param chunks: 文本块流
    :param show_thinking: 是否展示思考内容
    :param show_tool_hints: 是否展示工具提示
    :return:
    """
    async with aclosing(_iter_sse_frames(chunks)) as frames:
        async for frame in frames:
            if _keep_channel_sse_frame(frame, show_thinking=show_thinking, show_tool_hints=show_tool_hints):
                yield f'{frame}\n\n'


def filter_channel_stream(
    response: StreamingResponse,
    *,
    show_thinking: bool,
    show_tool_hints: bool,
) -> StreamingResponse:
    """
    按通道开关过滤 IM 流式事件，不影响 Web 重连订阅

    :param response: AG-UI 事件流
    :param show_thinking: 是否展示思考过程
    :param show_tool_hints: 是否展示工具调用提示
    :return:
    """
    if show_thinking and show_tool_hints:
        return response
    return StreamingResponse(
        _iter_filtered_frames(
            response.body_iterator,
            show_thinking=show_thinking,
            show_tool_hints=show_tool_hints,
        ),
        status_code=response.status_code,
        media_type=response.media_type,
        headers=dict(response.headers),
    )


async def collect_channel_reply(response: StreamingResponse) -> str:  # ruff: ignore[complex-structure]
    """
    消费通道 AG-UI 事件流，生成可发送的文本回复

    :param response: 已按通道显示设置过滤的事件流
    :return:
    """
    text_parts: dict[str, list[str]] = {}
    thinking_parts: list[str] = []
    tool_hints: list[str] = []
    current_message_id = ''
    failure: str | None = None
    async with aclosing(_iter_sse_frames(response.body_iterator)) as frames:
        async for frame in frames:
            payload = _parse_sse_payload(frame)
            if payload is None:
                continue
            event_type = payload.get('type')
            if event_type == EventType.TEXT_MESSAGE_START:
                current_message_id = str(payload.get('messageId') or '')
            elif event_type in {EventType.TEXT_MESSAGE_CONTENT, EventType.TEXT_MESSAGE_CHUNK}:
                content = payload.get('delta') or payload.get('content')
                if isinstance(content, str) and content:
                    message_id = str(payload.get('messageId') or current_message_id)
                    text_parts.setdefault(message_id, []).append(content)
            elif event_type in {
                EventType.THINKING_TEXT_MESSAGE_CONTENT,
                EventType.REASONING_MESSAGE_CONTENT,
                EventType.REASONING_MESSAGE_CHUNK,
            }:
                content = payload.get('delta') or payload.get('content')
                if isinstance(content, str) and content:
                    thinking_parts.append(content)
            elif event_type == EventType.TOOL_CALL_START:
                tool_name = payload.get('toolCallName')
                if isinstance(tool_name, str) and tool_name:
                    tool_hints.append(f'正在调用 {tool_name}')
            elif event_type == EventType.RUN_ERROR and failure is None:
                message = payload.get('message')
                failure = message.strip() if isinstance(message, str) and message.strip() else '模型运行失败'

    if failure is not None:
        return f'回复生成失败：{failure}'
    sections: list[str] = []
    if thinking_parts:
        sections.append('思考：\n' + ''.join(thinking_parts))
    if tool_hints:
        sections.append('\n'.join(tool_hints))
    sections.extend(''.join(parts) for parts in text_parts.values())
    return '\n\n'.join(sections).strip()
