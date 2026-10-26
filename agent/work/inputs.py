from collections.abc import Sequence
from typing import Any

from ag_ui.core import Message, RunAgentInput, Tool, ToolMessage, UserMessage
from pydantic_ai import (
    AgentRunResult,
    DeferredToolRequests,
    DeferredToolResults,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolFailed,
    ToolReturn,
    ToolReturnPart,
)
from pydantic_ai.ui.ag_ui import AGUIAdapter

from backend.common.exception import errors
from backend.database.db import uuid4_str
from backend.plugin.ai_buddy.agent.work.types import ChatAgent
from backend.plugin.ai_buddy.dataclasses import ChatRunContext
from backend.plugin.ai_buddy.schema.chat import AIBuddyForwardedPropsParam, parse_forwarded_props


def build_run_context(
    *,
    run_input: RunAgentInput,
    forwarded_props: AIBuddyForwardedPropsParam | None = None,
    default_conversation_id: str | None = None,
    expected_conversation_id: str | None = None,
) -> ChatRunContext:
    """
    补全 AG-UI 运行参数并保留当前轮用户输入

    :param run_input: 原生 AG-UI 运行参数
    :param forwarded_props: 已校验的聊天扩展参数
    :param default_conversation_id: 默认对话 ID
    :param expected_conversation_id: 路径中的对话 ID
    :return:
    """
    conversation_id = run_input.thread_id or default_conversation_id or uuid4_str()
    if expected_conversation_id is not None and conversation_id != expected_conversation_id:
        raise errors.RequestError(msg='请求体中的对话 ID 与路径不一致')
    resolved_props = parse_forwarded_props(
        forwarded_props.model_copy(deep=True) if forwarded_props is not None else run_input.forwarded_props
    )
    tool_messages: list[ToolMessage] = []
    for message in reversed(run_input.messages):
        if not isinstance(message, ToolMessage):
            break
        tool_messages.append(message)
    tool_messages.reverse()
    current_message = next(
        (message for message in reversed(run_input.messages) if isinstance(message, UserMessage)), None
    )
    current_messages = tool_messages or (
        [current_message] if current_message is not None and not run_input.resume else []
    )
    resolved_input = RunAgentInput.model_validate(
        {
            **run_input.model_dump(mode='python'),
            'thread_id': conversation_id,
            'run_id': run_input.run_id or uuid4_str(),
            'messages': [message.model_dump(mode='python') for message in current_messages],
            'forwarded_props': resolved_props.model_dump(mode='json'),
        },
    )
    return ChatRunContext(
        conversation_id=conversation_id,
        forwarded_props=resolved_props,
        run_input=resolved_input,
    )


def decode_input_messages(*, messages: Sequence[Message]) -> list[ModelMessage]:
    """
    通过官方 AG-UI 转换器解析用户输入

    :param messages: 原生 AG-UI 消息列表
    :return:
    """
    user_messages = [message for message in messages if isinstance(message, UserMessage)]
    return AGUIAdapter.load_messages(user_messages, preserve_file_data=True)


def sanitize_input_messages(
    *,
    agent: ChatAgent,
    run_input: RunAgentInput,
    messages: Sequence[ModelMessage],
) -> list[ModelMessage]:
    """
    按官方 AG-UI 文件规则清洗本轮模型消息

    :param agent: 聊天代理
    :param run_input: 原生 AG-UI 运行参数
    :param messages: 模型消息列表
    :return:
    """
    adapter = AGUIAdapter(
        agent=agent,
        run_input=run_input,
        allow_uploaded_files=True,
        preserve_file_data=True,
    )
    return adapter.sanitize_messages(messages)


def mark_frontend_tool_requests(*, result: AgentRunResult[Any], tools: Sequence[Tool]) -> None:
    """
    在服务端消息中记录本轮等待客户端执行的工具调用

    :param result: 原生代理运行结果
    :param tools: 本轮 AG-UI 前端工具定义
    :return:
    """
    if not isinstance(result.output, DeferredToolRequests):
        return
    tool_names = {tool.name for tool in tools}
    pending_calls = {call.tool_call_id: call.tool_name for call in result.output.calls if call.tool_name in tool_names}
    if not pending_calls:
        return
    for message in result.new_messages():
        if not isinstance(message, ModelResponse):
            continue
        message_calls = {
            part.tool_call_id: part.tool_name
            for part in message.parts
            if isinstance(part, ToolCallPart) and pending_calls.get(part.tool_call_id) == part.tool_name
        }
        if message_calls:
            message.metadata = {**(message.metadata or {}), 'ag_ui_frontend_tool_calls': message_calls}


def build_frontend_tool_results(
    *,
    run_input: RunAgentInput,
    message_history: Sequence[ModelMessage],
) -> DeferredToolResults | None:
    """
    按服务端待执行调用校验并解析原生 AG-UI 前端工具结果

    :param run_input: 原生 AG-UI 运行参数
    :param message_history: 服务端模型消息历史
    :return:
    """
    tool_messages = [message for message in run_input.messages if isinstance(message, ToolMessage)]
    if not tool_messages:
        return None
    response_index = next(
        (
            index
            for index in range(len(message_history) - 1, -1, -1)
            if isinstance(message_history[index], ModelResponse)
        ),
        None,
    )
    if response_index is None:
        raise errors.RequestError(msg='当前对话没有待执行的前端工具调用')
    response = message_history[response_index]
    assert isinstance(response, ModelResponse)
    frontend_calls = (response.metadata or {}).get('ag_ui_frontend_tool_calls', {})
    if not isinstance(frontend_calls, dict):
        raise errors.RequestError(msg='前端工具调用记录非法')
    resolved_ids = {
        part.tool_call_id
        for message in message_history[response_index + 1 :]
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_call_id
    }
    pending_calls = {
        part.tool_call_id: part.tool_name
        for part in response.parts
        if isinstance(part, ToolCallPart)
        and frontend_calls.get(part.tool_call_id) == part.tool_name
        and part.tool_call_id not in resolved_ids
    }
    received: set[str] = set()
    for message in tool_messages:
        if message.tool_call_id not in pending_calls or message.tool_call_id in received:
            raise errors.RequestError(msg='前端工具结果与待执行调用不一致')
        received.add(message.tool_call_id)

    parsed_messages = AGUIAdapter.load_messages(
        [*AGUIAdapter.dump_messages([response], preserve_file_data=True), *tool_messages],
        preserve_file_data=True,
    )
    tool_errors = {message.tool_call_id: message.error for message in tool_messages if message.error}
    results = DeferredToolResults()
    for message in parsed_messages:
        if not isinstance(message, ModelRequest):
            continue
        for part in message.parts:
            if not isinstance(part, ToolReturnPart) or part.tool_call_id not in received:
                continue
            results.calls[part.tool_call_id] = (
                ToolReturn(part.content)
                if part.outcome == 'success'
                else ToolFailed(tool_errors.get(part.tool_call_id) or str(part.content))
            )
    return results
