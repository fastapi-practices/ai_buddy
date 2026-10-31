from __future__ import annotations

import asyncio
import json
import math

from typing import TYPE_CHECKING, Any

from acp.exceptions import RequestError as ACPRequestError

from backend.plugin.ai_buddy.agent.coding.protocol.acp.models import ACPConfig, ACPError
from backend.plugin.ai_buddy.agent.coding.protocol.acp.tool_adapter import (
    format_close_response,
    format_final_response,
    format_permission_required,
    render_event_text,
)
from backend.plugin.ai_buddy.agent.coding.tools import BoundAgentTool
from backend.plugin.ai_buddy.agent.coding.types import AgentToolSpec

if TYPE_CHECKING:
    from backend.plugin.ai_buddy.agent.coding.protocol.acp.service import ACPService

_ACP_RUNNER_DESCRIPTION = """Delegate tasks to an external ACP-compatible coding agent runtime.

Use this tool to collaborate with configured external agents such as
OpenCode, CodeBuddy, Claude Code, Codex, Kimi Code, Cursor CLI, or Pi.

Workflow:
1. action='list' — show enabled runners and session states.
2. action='start', runner='...', message='...' — open a new session in the user-selected local workspace.
3. action='message', runner='...', message='...' — continue the session.
4. When [permission_required] appears, ask the user which option to pick,
   then action='respond', runner='...', message='<exact option id>'.
5. action='close', runner='...' — close the session.
"""


def build_acp_runner_tool(*, service: ACPService, config: ACPConfig, thread_id: str) -> BoundAgentTool:
    """
    绑定到当前编码对话的 acp_runner 工具

    :param service: ACP 服务
    :param config: runner 配置
    :param thread_id: 对话 ID
    :return:
    """

    async def handler(arguments: dict[str, Any]) -> str:
        """
        将工具调用参数交给已绑定的运行环境

        :param arguments: 工具调用参数
        :return:
        """
        return await run_acp_runner(
            service=service,
            config=config,
            thread_id=thread_id,
            action=str(arguments.get('action') or ''),
            runner=str(arguments.get('runner') or ''),
            message=str(arguments.get('message') or ''),
            max_runtime=arguments.get('max_runtime', 300),
        )

    return BoundAgentTool(
        spec=AgentToolSpec(
            name='acp_runner',
            description=_ACP_RUNNER_DESCRIPTION,
            parameters={
                'type': 'object',
                'properties': {
                    'action': {
                        'type': 'string',
                        'description': 'list / status / start / message / respond / close',
                    },
                    'runner': {'type': 'string', 'description': 'runner 名，list 可不传'},
                    'message': {
                        'type': 'string',
                        'description': 'start/message 的任务文本，或 respond 的 option id',
                    },
                    'max_runtime': {'type': 'number', 'description': '单轮超时秒数，默认 300'},
                },
                'required': ['action'],
            },
            mutating=True,
        ),
        handler=handler,
    )


async def run_acp_runner(  # ruff: ignore[complex-structure]
    *,
    service: ACPService,
    config: ACPConfig,
    thread_id: str,
    action: str,
    runner: str = '',
    message: str = '',
    max_runtime: float | None = 300,
) -> str:
    """
    执行 acp_runner 动作

    :param service: ACP 服务
    :param config: runner 配置
    :param thread_id: 对话 ID
    :param action: 动作
    :param runner: runner 名
    :param message: 提示或 option id
    :param max_runtime: 超时
    :return:
    """
    action_name = str(action or '').strip().lower()
    runner_name = str(runner or '').strip()
    message_text = str(message or '')
    if action_name not in {'list', 'status', 'start', 'message', 'respond', 'close'}:
        return '错误：action 必须是以下值之一：list、status、start、message、respond、close'
    if action_name not in {'list', 'status'} and not runner_name:
        return '错误：runner 不能为空'
    if action_name in {'message', 'respond'} and not message_text:
        if action_name == 'message':
            return "错误：message 不能为空，请先使用 action='start' 开始新会话"
        return '错误：message 不能为空，respond 时请传入准确的权限选项 ID'

    if action_name == 'list' or (action_name == 'status' and not runner_name):
        runners = config.enabled_runner_names()
        if not runners:
            return '未配置已启用的 ACP 执行器'
        lines = ['Available external ACP runners:']
        for name in runners:
            details: list[str] = []
            if await service.session_is_open(thread_id=thread_id, runner=name):
                details.append('session: open')
            pending = await service.get_pending_permission(thread_id=thread_id, runner=name)
            if pending is not None:
                details.append('task: permission_required')
            lines.append(f'- {name}' + (f' ({", ".join(details)})' if details else ''))
        return '\n'.join(lines)
    if action_name == 'status':
        runner_config = config.runners.get(runner_name)
        if runner_config is None or not runner_config.enabled:
            reason = '未配置' if runner_config is None else '已禁用'
            return f"错误：执行器 '{runner_name}' {reason}"

        session_is_open = await service.session_is_open(thread_id=thread_id, runner=runner_name)
        pending = await service.get_pending_permission(thread_id=thread_id, runner=runner_name)
        state = ('waiting_for_permission' if pending is not None else 'open') if session_is_open else 'closed'
        lines = [f'runner: {runner_name}', f'session: {state}']
        if pending is not None:
            lines.extend(('', format_permission_required(pending)))
        return '\n'.join(lines)
    if action_name == 'close':
        existing = await service.session_is_open(thread_id=thread_id, runner=runner_name)
        await service.close_thread_session(thread_id=thread_id, runner=runner_name)
        return format_close_response(runner_name=runner_name, closed=existing)

    timeout_seconds = None
    if max_runtime is not None:
        try:
            timeout_seconds = float(max_runtime)
        except (TypeError, ValueError):
            return '错误：max_runtime 必须是秒数'
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            return '错误：max_runtime 必须是有限且大于 0 的数值'
    if runner_name not in config.runners or not config.runners[runner_name].enabled:
        enabled = ', '.join(config.enabled_runner_names()) or '(none)'
        return f"错误：执行器 '{runner_name}' 不可用。已启用的执行器：{enabled}"
    if action_name == 'start' and await service.session_is_open(thread_id=thread_id, runner=runner_name):
        return f"错误：执行器 '{runner_name}' 的 ACP 会话已打开，请改用 action='message'"

    chunks: list[str] = []
    final_event: dict[str, Any] | None = None

    async def on_message(payload: dict[str, Any], _is_last: object) -> None:
        """
        收集 ACP 工具进度及最终输出

        :param payload: ACP 事件载荷
        :param _is_last: 是否为本轮最后一条消息
        :return:
        """
        nonlocal final_event
        if payload.get('type') == 'text' and payload.get('is_chunk'):
            return
        if str(payload.get('type') or '').lower() == 'text':
            final_event = payload
        else:
            text = render_event_text(payload)
            if text:
                chunks.append(text)
        await asyncio.sleep(0)

    async def execute() -> dict[str, Any]:
        """在超时任务内执行或恢复 ACP 提示"""
        if action_name == 'respond':
            session_id = await service.get_session_id(thread_id=thread_id, runner=runner_name)
            if session_id is None:
                raise ACPError(f"当前线程没有绑定执行器 '{runner_name}' 的 ACP 会话")
            pending = await service.get_pending_permission(thread_id=thread_id, runner=runner_name)
            if pending is None:
                raise ACPError(f"执行器 '{runner_name}' 的当前 ACP 会话不在等待权限审批")
            return await service.resume_permission(
                acp_session_id=session_id,
                option_id=message_text.strip(),
                on_message=on_message,
            )
        return await service.run_turn(
            thread_id=thread_id,
            runner=runner_name,
            prompt_blocks=[{'type': 'text', 'text': message_text or ('hi' if action_name == 'start' else '')}],
            cwd=service.cwd,
            on_message=on_message,
            restart=action_name == 'start',
            require_existing=action_name == 'message',
        )

    try:
        result = (
            await execute() if timeout_seconds is None else await asyncio.wait_for(execute(), timeout=timeout_seconds)
        )
    except TimeoutError:
        stopped = await service.cancel_turn(thread_id=thread_id, runner=runner_name)
        if not stopped:
            await service.close_thread_session(thread_id=thread_id, runner=runner_name)
        return f"执行器 '{runner_name}' 的 ACP 轮次达到 max_runtime，已中断。" + (
            "会话仍保持打开，请使用 action='message' 继续" if stopped else "会话已关闭，请使用 action='start' 重新开始"
        )
    except asyncio.CancelledError:
        await service.close_thread_session(thread_id=thread_id, runner=runner_name)
        raise
    except ImportError as exc:
        return f'未安装 ACP 支持：{exc}。请安装 agent-client-protocol'
    except (ACPError, ValueError) as exc:
        return f'错误：{exc}'
    except ACPRequestError as exc:
        return f'外部 Agent 返回错误：{exc}'
    except OSError as exc:
        return f'ACP 执行错误：{exc}'

    if result.get('status') == 'permission_required':
        suspended = result.get('suspended_permission')
        body = '\n\n'.join(chunks).strip()
        permission_text = format_permission_required(suspended) if suspended is not None else ''
        if body and permission_text:
            return f'{body}\n\n{permission_text}'
        return permission_text or body or '需要权限审批'
    event = result.get('event') if isinstance(result.get('event'), dict) else final_event
    final = format_final_response(runner_name=runner_name, final_event=event)
    stop_reason = result.get('stop_reason')
    if stop_reason != 'end_turn':
        chunks.append(f'ACP 轮次未正常完成，停止原因：{stop_reason or "未上报"}，不得据此宣称任务已完成')
    usage = result.get('usage')
    usage_text = (
        f'ACP Agent 上报用量（独立于 Buddy 主模型）：{json.dumps(usage, ensure_ascii=False)}'
        if usage is not None
        else 'ACP Agent 未上报用量，不按零用量计'
    )
    return '\n\n'.join([*chunks, final, usage_text]).strip()
