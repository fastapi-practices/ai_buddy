import base64
import hashlib

from typing import Any

from acp import audio_block, image_block, resource_block, text_block
from acp.schema import (
    AudioContentBlock,
    BlobResourceContents,
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    PromptCapabilities,
    TextContentBlock,
)
from pydantic_ai.messages import BinaryContent

from backend.plugin.ai_buddy.agent.coding.attachments import input_attachment_path
from backend.plugin.ai_buddy.agent.coding.protocol.acp.models import ACPError

type AcpPromptBlock = TextContentBlock | ImageContentBlock | AudioContentBlock | EmbeddedResourceContentBlock


def build_acp_prompt(
    *,
    blocks: list[dict[str, Any]],
    attachments: tuple[BinaryContent, ...],
    capabilities: PromptCapabilities | None,
    imported_hashes: frozenset[str] = frozenset(),
) -> list[AcpPromptBlock]:
    """根据 ACP 握手能力转换本轮文本和原始附件

    :param blocks: 主代理委托文本
    :param attachments: 用户附件字节
    :param capabilities: 外部 Agent 声明的提示能力
    :param imported_hashes: 已导入当前本机工作区的附件摘要
    :return:
    """
    if any(block.get('type') != 'text' for block in blocks):
        raise ACPError('委托指令必须是文本提示块')
    prompt: list[AcpPromptBlock] = [text_block(str(block.get('text', ''))) for block in blocks]
    remaining = 5 * 1024 * 1024
    for attachment in attachments:
        digest = hashlib.sha256(attachment.data).hexdigest()
        native_supported = (
            attachment.media_type.startswith('text/')
            or (attachment.is_image and bool(getattr(capabilities, 'image', False)))
            or (attachment.is_audio and bool(getattr(capabilities, 'audio', False)))
            or bool(getattr(capabilities, 'embedded_context', False))
        )
        if digest in imported_hashes and (not native_supported or len(attachment.data) > remaining):
            prompt.append(
                text_block(
                    f'附件 {attachment.identifier} 已导入当前工作区 inbound/，文件名以 {digest}- 开头。'
                    '请使用本地文件工具读取，具体路径以用户消息附带的导入记录为准'
                )
            )
            continue
        remaining -= len(attachment.data)
        if remaining < 0:
            raise ACPError('ACP 内联附件总大小超过 5 MiB，且超额附件未导入本机工作区，请拆分发送')
        uri = f'buddy-input:///{input_attachment_path(attachment)}'
        encoded = base64.b64encode(attachment.data).decode('ascii')
        if attachment.media_type.startswith('text/'):
            try:
                prompt.append(text_block(f'附件 {attachment.identifier}:\n{attachment.data.decode("utf-8")}'))
            except UnicodeDecodeError as exc:
                raise ACPError('文本附件不是 UTF-8，请转换编码后重新发送') from exc
        elif attachment.is_image and getattr(capabilities, 'image', False):
            prompt.append(image_block(encoded, attachment.media_type, uri=uri))
        elif attachment.is_audio and getattr(capabilities, 'audio', False):
            prompt.append(audio_block(encoded, attachment.media_type))
        elif getattr(capabilities, 'embedded_context', False):
            prompt.append(resource_block(BlobResourceContents(uri=uri, blob=encoded, mime_type=attachment.media_type)))
        else:
            raise ACPError(f'外部 Agent 未声明支持附件 {attachment.identifier}（{attachment.media_type}），附件未发送')
    return prompt


def render_event_text(event: dict[str, Any]) -> str | None:
    """
    把 ACP 客户端事件收成工具可见文本

    :param event: 事件
    :return:
    """
    event_type = str(event.get('type') or '').lower()
    if event_type == 'text':
        text = str(event.get('text') or '').strip()
        return f'[assistant]\n{text}' if text else None
    if event_type.startswith('tool_'):
        kind = str(event.get('kind') or '').strip()
        detail = str(event.get('detail') or event.get('title') or '').strip()
        return f'[tool_call] {kind} ({detail})' if kind and detail else None
    if event_type == 'status':
        status = str(event.get('status') or 'unknown')
        if status == 'run_finished':
            return None
        summary = str(event.get('summary') or '').strip()
        if status == 'agent_thinking':
            return summary or 'agent thinking...'
        parts = [f'[status] {status}']
        if summary:
            parts.append(summary)
        return '\n'.join(parts)
    if event_type == 'permission_request':
        title = str(event.get('title') or event.get('reason') or 'permission request')
        options = event.get('options') or []
        rendered = [
            str(opt.get('title') or opt.get('name') or opt.get('optionId') or 'option')
            + (f' ({option_id})' if (option_id := str(opt.get('optionId') or '')) else '')
            for opt in options
            if isinstance(opt, dict)
        ]
        lines = [f'[permission_request] {title}']
        if rendered:
            lines.append(f'options: {", ".join(rendered)}')
        return '\n'.join(lines)
    if event_type == 'error':
        message_text = str(event.get('message') or '未知错误')
        return f'[错误] {message_text}' if message_text else None
    return None


def format_permission_required(suspended: Any) -> str:
    """
    把挂起的权限请求格式化成工具输出

    :param suspended: SuspendedPermission
    :return:
    """
    title = str(getattr(suspended, 'summary', None) or getattr(suspended, 'tool_name', None) or 'permission request')
    lines = [f'[permission_required] {title}', "Choose an option id and call acp_runner(action='respond', ...):"]
    for opt in getattr(suspended, 'options', []) or []:
        if not isinstance(opt, dict):
            continue
        name = str(opt.get('title') or opt.get('name') or opt.get('optionId') or 'option')
        option_id = str(opt.get('optionId') or '')
        lines.append(f'- {name}' + (f' (id={option_id})' if option_id else ''))
    return '\n'.join(lines)


def format_close_response(*, runner_name: str, closed: bool) -> str:
    """
    格式化 ACP 会话关闭结果

    :param runner_name: ACP 执行器名称
    :param closed: 是否确实关闭了会话
    :return:
    """
    if closed:
        return f"已关闭执行器 '{runner_name}' 的 ACP 会话"
    return f"执行器 '{runner_name}' 没有打开的 ACP 会话"


def format_final_response(*, runner_name: str, final_event: dict[str, Any] | None) -> str:
    """
    格式化 ACP 最终回复或错误

    :param runner_name: ACP 执行器名称
    :param final_event: ACP 最终事件
    :return:
    """
    header = f'runner: {runner_name} (user local agent)'
    if final_event and str(final_event.get('type') or '').lower() == 'text':
        text = str(final_event.get('text') or '').strip()
        if text:
            return f'{header}\n\n[assistant]\n{text}'
    if final_event and str(final_event.get('type') or '').lower() == 'error':
        return f'{header}\n\n[错误] {final_event.get("message", "未知错误")}'
    return f'{header}\n\n(助手未返回文本)'
