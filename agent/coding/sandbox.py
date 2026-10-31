from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import re

from datetime import UTC, datetime, timedelta
from pathlib import PureWindowsPath
from posixpath import join, normpath
from typing import TYPE_CHECKING, Any, Literal, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import anyio

from opensandbox.adapters import AdapterFactory
from opensandbox.exceptions import SandboxApiException, SandboxConnectionException, SandboxTimeoutException
from opensandbox.models.execd import ExecutionHandlers, ExecutionInit, OutputMessage, RunCommandOpts
from opensandbox.models.filesystem import ContentReplaceEntry, DirectoryListEntry, MoveEntry, WriteEntry
from pydantic import TypeAdapter, ValidationError

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.enums import (
    AIBuddyCommandReason,
    AIBuddyExecutionBackend,
    AIBuddyExecutionMethod,
    AIBuddyPermissionMode,
)
from backend.plugin.ai_buddy.schema.command import (
    COMMAND_OUTPUT_MAX_BYTES,
    AIBuddyBackgroundTaskDetail,
    AIBuddyCommandParam,
    AIBuddyCommandResult,
)
from backend.plugin.ai_buddy.schema.execution import AIBuddyExecutionFileEntry

if TYPE_CHECKING:
    from opensandbox import Sandbox

    from backend.plugin.ai_buddy.agent.coding.execution_bridge import ExecutionBridge


WORKSPACE_ROOT = '/workspace'
INPUT_ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024
LIVE_SANDBOXES: dict[str, CodingSandbox] = {}


def _git_command(operation: Literal['status', 'diff'], *, scope: Literal['all', 'staged', 'unstaged'] = 'all') -> str:
    """
    构建限定当前目录仓库的只读 Git 命令

    :param operation: Git 操作
    :param scope: 差异范围
    :return:
    """
    if scope not in ('all', 'staged', 'unstaged'):
        raise errors.RequestError(msg='Git 差异范围无效')
    prefix = (
        'git_query() { /usr/bin/env -i PATH=/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin '
        'LANG=C LC_ALL=C GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_NO_LAZY_FETCH=1 '
        'git --no-optional-locks --no-pager --git-dir=.git --work-tree=. '
        '-c color.ui=false -c core.fsmonitor=false -c core.excludesfile=/dev/null '
        '-c core.attributesfile=/dev/null -c protocol.allow=never "$@"; }; '
        'if [ ! -d .git ] || [ -L .git ] || [ -e .git/commondir ] '
        '|| [ -e .git/objects/info/alternates ] || [ -e .git/objects/info/http-alternates ]; then '
        'printf "%s\\n" "当前工作区根目录没有独立 Git 仓库，尚不支持外部 Git 元数据"; exit 1; fi; '
        'metadata_links=$(/usr/bin/find .git -type l -print -quit); '
        'if [ "$?" -ne 0 ] || [ -n "$metadata_links" ]; then '
        'printf "%s\\n" "Git 元数据不能包含符号链接"; exit 1; fi; '
        'for config_file in .git/config .git/config.worktree; do '
        'git_query --git-dir=/dev/null config --file "$config_file" --no-includes '
        '--name-only --get-regexp "^(include|includeif)\\.|^filter\\..*\\.(clean|smudge|process)$" '
        '>/dev/null; config_status=$?; if [ "$config_status" -ne 1 ]; then '
        'printf "%s\\n" "Git 配置无效、引用了其他配置文件或包含外部过滤器"; exit 1; fi; done; '
    )
    if operation == 'status':
        return prefix + 'git_query status --short --branch --untracked-files=all --ignore-submodules=all'
    diff = 'git_query diff --no-ext-diff --no-textconv --ignore-submodules=all --unified=3'
    if scope == 'staged':
        return prefix + diff + ' --cached --'
    if scope == 'unstaged':
        return prefix + diff + ' --'
    return (
        prefix
        + 'printf "%s\\n" "已暂存差异："; '
        + diff
        + ' --cached -- && printf "%s\\n" "未暂存差异：" && '
        + diff
        + ' --'
    )


class CodingSandbox(Protocol):
    """编码对话沙箱"""

    execution_backend: AIBuddyExecutionBackend
    user_id: int | None
    permission_mode: AIBuddyPermissionMode
    cwd: str

    async def stop(self) -> None:
        """关闭沙箱资源"""
        ...

    async def list_entries(self, *, path: str = '.') -> list[dict[str, object]]:
        """
        列出工作区目录项

        :param path: 工作区相对路径
        :return:
        """
        ...

    async def read_file(
        self, *, path: str, offset: int = 0, limit: int | None = None, line_numbers: bool = True
    ) -> str:
        """
        读取工作区文件内容

        :param path: 文件路径
        :param offset: 起始行号
        :param limit: 最大行数
        :param line_numbers: 是否包含行号
        :return:
        """
        ...

    async def write_file(self, *, path: str, content: str) -> str:
        """
        写入工作区文件

        :param path: 文件路径
        :param content: 文件内容
        :return:
        """
        ...

    async def write_input_file(self, *, path: str, content: bytes) -> str:
        """
        将用户输入附件写入工作区 inbound 目录

        :param path: 工作区相对路径
        :param content: 文件内容
        :return:
        """
        ...

    async def read_bytes(self, *, path: str, max_bytes: int) -> bytes:
        """
        读取工作区文件原始字节，超过上限时拒绝读取

        :param path: 文件路径
        :param max_bytes: 字节数上限
        :return:
        """
        ...

    async def edit_file(self, *, path: str, old_text: str, new_text: str) -> str:
        """
        替换工作区文件内容

        :param path: 文件路径
        :param old_text: 待替换的原文本
        :param new_text: 替换后的新文本
        :return:
        """
        ...

    async def run_bash(self, *, command: str) -> str:
        """
        执行工作区命令

        :param command: 执行命令
        :return:
        """
        ...

    async def git_status(self) -> str:
        """读取工作区 Git 状态"""
        ...

    async def run_command(self, *, command: str, timeout: float | None = None) -> AIBuddyCommandResult:
        """
        执行受控命令并返回退出码、输出、耗时、截断和取消状态

        :param command: 已确认的命令
        :param timeout: 超时秒数
        :return:
        """
        ...

    async def run_tests(self, *, command: str, timeout: float | None = None) -> AIBuddyCommandResult:
        """
        执行显式测试命令并返回结构化事实

        :param command: 已确认的测试命令
        :param timeout: 执行时限
        :return:
        """
        ...

    async def git_diff(self, *, scope: Literal['all', 'staged', 'unstaged'] = 'all') -> str:
        """
        按范围读取工作区未提交差异

        :param scope: 差异范围
        :return:
        """
        ...

    async def run_background(self, *, command: str, env: dict[str, str] | None = None) -> str:
        """
        启动工作区后台命令

        :param command: 执行命令
        :param env: 环境变量
        :return:
        """
        ...

    async def get_background_task(self, *, task_id: str, cursor: int | None = None) -> AIBuddyBackgroundTaskDetail:
        """
        查询后台命令状态并增量读取输出

        :param task_id: 后台命令任务 ID
        :param cursor: 日志游标
        :return:
        """
        ...

    async def stop_background(self, *, task_id: str) -> None:
        """
        中断后台命令

        :param task_id: 后台命令任务 ID
        :return:
        """
        ...

    async def get_endpoint(self, port: int) -> tuple[str, dict[str, str]]:
        """
        获取工作区进程访问地址

        :param port: 端口号
        :return:
        """
        ...


def resolve_sandbox_path(path: str) -> str:
    """
    将用户路径解析到沙箱工作区内，禁止逃逸

    :param path: 用户给出的路径
    :return:
    """
    raw = (path or '').strip() or '.'
    full = raw if raw.startswith('/') else join(WORKSPACE_ROOT, raw)
    normalized = normpath(full)
    if normalized != WORKSPACE_ROOT and not normalized.startswith(f'{WORKSPACE_ROOT}/'):
        raise errors.RequestError(msg='路径超出工作区')
    return normalized


def get_live_sandbox(conversation_id: str) -> CodingSandbox | None:
    """
    获取对话当前沙箱

    :param conversation_id: 对话 ID
    :return:
    """
    return LIVE_SANDBOXES.get(conversation_id)


def _desktop_path(path: str) -> str:
    """
    校验桌面工作区相对路径并阻止目录逃逸

    :param path: 文件路径
    :return:
    """
    raw = (path or '').strip() or '.'
    normalized = normpath(raw.replace('\\', '/'))
    if '\0' in raw or PureWindowsPath(raw).drive or normalized.startswith(('/', '../')) or normalized == '..':
        raise errors.RequestError(msg='路径超出桌面工作区，请使用相对路径')
    return normalized


class DesktopBridgeWorkspace:
    """仅通过桌面连接执行的本机 OS 沙箱工作区"""

    def __init__(self, bridge: ExecutionBridge, *, conversation_id: str) -> None:
        """
        绑定桌面执行连接及工作区限制

        :param bridge: 桌面执行连接
        :param conversation_id: 对话 ID
        :return:
        """
        self.bridge = bridge
        self._conversation_id = conversation_id
        self.execution_backend = bridge.record['backend']
        self.user_id = bridge.record['user_id']
        self.permission_mode = bridge.record['permission_mode']
        self.cwd = bridge.record['cwd']
        self._max_file_bytes = bridge.record['limits']['max_file_bytes']
        self._stopped = False

    async def stop(self) -> None:
        """请求桌面端结束进程树，无论响应如何都撤销连接"""
        if self._stopped:
            return
        self._stopped = True
        if LIVE_SANDBOXES.get(self._conversation_id) is self:
            LIVE_SANDBOXES.pop(self._conversation_id, None)
        try:
            async with asyncio.timeout(5):
                await self.bridge.request(AIBuddyExecutionMethod.stop, {}, timeout=5)
        except (errors.RequestError, ConnectionError, TimeoutError):
            pass
        finally:
            await self.bridge.close()

    async def list_entries(self, *, path: str = '.') -> list[dict[str, object]]:
        """
        列出工作区相对路径下的目录项

        :param path: 文件路径
        :return:
        """
        result = await self.bridge.request(AIBuddyExecutionMethod.list_files, {'path': _desktop_path(path)})
        try:
            entries = TypeAdapter(list[AIBuddyExecutionFileEntry]).validate_python(result)
        except ValidationError as exc:
            raise errors.RequestError(msg='桌面端返回了无效的目录列表') from exc
        return [entry.model_dump() for entry in entries]

    async def _text(self, method: AIBuddyExecutionMethod, params: dict[str, object]) -> str:
        """
        调用桌面工具并校验文本结果

        :param method: 方法名称
        :param params: 方法参数
        :return:
        """
        result = await self.bridge.request(method, params)
        if not isinstance(result, str):
            raise errors.RequestError(msg='桌面端返回了无效的文本结果')
        return result

    async def read_file(
        self, *, path: str, offset: int = 0, limit: int | None = None, line_numbers: bool = True
    ) -> str:
        """
        按行范围读取工作区文件

        :param path: 文件路径
        :param offset: 起始偏移量
        :param limit: 数量上限
        :param line_numbers: 是否包含行号
        :return:
        """
        return await self._text(
            AIBuddyExecutionMethod.read_file,
            {
                'path': _desktop_path(path),
                'offset': max(offset, 0),
                'limit': None if limit is None else max(limit, 0),
                'line_numbers': line_numbers,
            },
        )

    async def write_file(self, *, path: str, content: str) -> str:
        """
        在大小限制内写入工作区文件

        :param path: 文件路径
        :param content: 文本内容
        :return:
        """
        if len(content.encode()) > self._max_file_bytes:
            raise errors.RequestError(msg='写入内容超过文件大小上限')
        return await self._text(AIBuddyExecutionMethod.write_file, {'path': _desktop_path(path), 'content': content})

    async def write_input_file(self, *, path: str, content: bytes) -> str:
        """
        通过已协商的字节协议导入用户附件

        :param path: 受限的 inbound 路径
        :param content: 附件字节
        :return:
        """
        if len(content) > INPUT_ATTACHMENT_MAX_BYTES:
            raise errors.RequestError(msg='附件超过 10 MiB 导入上限')
        return await self._text(
            AIBuddyExecutionMethod.write_input_file,
            {
                'path': path,
                'content_base64': base64.b64encode(content).decode('ascii'),
                'sha256': hashlib.sha256(content).hexdigest(),
            },
        )

    async def read_bytes(self, *, path: str, max_bytes: int) -> bytes:
        """
        本机文件已在用户电脑上，不经桌面桥传回服务端

        :param path: 文件路径
        :param max_bytes: 字节数上限
        :return:
        """
        raise errors.RequestError(msg='本机工作区文件已保存在用户电脑上，无需交付到服务端')

    async def edit_file(self, *, path: str, old_text: str, new_text: str) -> str:
        """
        替换工作区文件中的指定内容

        :param path: 文件路径
        :param old_text: 待替换的原文本
        :param new_text: 替换后的新文本
        :return:
        """
        if max(len(old_text.encode()), len(new_text.encode())) > self._max_file_bytes:
            raise errors.RequestError(msg='编辑内容超过文件大小上限')
        return await self._text(
            AIBuddyExecutionMethod.edit_file, {'path': _desktop_path(path), 'old_text': old_text, 'new_text': new_text}
        )

    async def run_bash(self, *, command: str) -> str:
        """
        在工作区执行经过校验的命令

        :param command: 执行命令
        :return:
        """
        if not command.strip() or '\0' in command:
            raise errors.RequestError(msg='命令不能为空或包含空字符')
        return await self._text(AIBuddyExecutionMethod.run_bash, {'command': command.strip()})

    async def git_status(self) -> str:
        """读取桌面工作区 Git 状态"""
        return await self._text(AIBuddyExecutionMethod.git_status, {})

    async def run_command(self, *, command: str, timeout: float | None = None) -> AIBuddyCommandResult:
        """
        只向已协商能力的桌面端请求结构化命令执行

        :param command: 已确认的命令
        :param timeout: 超时秒数
        :return:
        """
        params = AIBuddyCommandParam(command=command)
        result = await self.bridge.request(
            AIBuddyExecutionMethod.run_command,
            {**params.model_dump(), **({'timeout_ms': max(1, int(timeout * 1000))} if timeout is not None else {})},
            timeout=timeout,
        )
        return AIBuddyCommandResult.model_validate(result)

    async def run_tests(self, *, command: str, timeout: float | None = None) -> AIBuddyCommandResult:
        """
        只向已协商能力的桌面端请求结构化测试执行

        :param command: 已确认的测试命令
        :param timeout: 执行时限
        :return:
        """
        params = AIBuddyCommandParam(command=command)
        result = await self.bridge.request(
            AIBuddyExecutionMethod.run_tests,
            {**params.model_dump(), **({'timeout_ms': max(1, int(timeout * 1000))} if timeout is not None else {})},
            timeout=timeout,
        )
        return AIBuddyCommandResult.model_validate(result)

    async def git_diff(self, *, scope: Literal['all', 'staged', 'unstaged'] = 'all') -> str:
        """
        按范围读取桌面工作区未提交差异

        :param scope: 差异范围
        :return:
        """
        if scope not in ('all', 'staged', 'unstaged'):
            raise errors.RequestError(msg='Git 差异范围无效')
        return await self._text(AIBuddyExecutionMethod.git_diff, {'scope': scope})

    async def run_background(self, *, command: str, env: dict[str, str] | None = None) -> str:
        """
        桌面端协议没有后台命令任务能力

        :param command: 执行命令
        :param env: 环境变量
        :return:
        """
        raise errors.RequestError(msg='桌面端尚未协商后台命令能力，请使用 OpenSandbox')

    async def get_background_task(self, *, task_id: str, cursor: int | None = None) -> AIBuddyBackgroundTaskDetail:
        """
        桌面端协议没有后台命令任务能力

        :param task_id: 后台命令任务 ID
        :param cursor: 日志游标
        :return:
        """
        raise errors.RequestError(msg='桌面端尚未协商后台命令能力，请使用 OpenSandbox')

    async def stop_background(self, *, task_id: str) -> None:
        """
        桌面端协议没有后台命令任务能力

        :param task_id: 后台命令任务 ID
        :return:
        """
        raise errors.RequestError(msg='桌面端尚未协商后台命令能力，请使用 OpenSandbox')

    async def get_endpoint(self, port: int) -> tuple[str, dict[str, str]]:
        """
        查询工作区进程的可访问端口地址

        :param port: 端口号
        :return:
        """
        if isinstance(port, bool) or not 1 <= port <= 65535:
            raise errors.RequestError(msg='端口必须在 1 到 65535 之间')
        await self.bridge.request(AIBuddyExecutionMethod.get_endpoint, {'port': port})
        raise errors.RequestError(msg='桌面端点不能用于服务器 HTTP 访问，尚未提供 HTTP 隧道，请使用 OpenSandbox')


class OpenSandboxWorkspace:
    """OpenSandbox 编码工作区"""

    def __init__(
        self,
        client: Sandbox,
        *,
        conversation_id: str,
        user_id: int | None = None,
        permission_mode: AIBuddyPermissionMode = AIBuddyPermissionMode.ask,
    ) -> None:
        """
        绑定远程沙箱及端口查询客户端

        :param client: 客户端
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param permission_mode: 权限模式
        :return:
        """
        self._client = client
        self._conversation_id = conversation_id
        self.execution_backend = AIBuddyExecutionBackend.sandbox
        self.cwd = WORKSPACE_ROOT
        self.user_id = user_id
        self.permission_mode = permission_mode
        self._endpoints = AdapterFactory(client.connection_config).create_sandbox_service()
        self._stopped = False

    async def stop(self) -> None:
        """关闭本进程的连接，沙箱实例保留供下一轮接回，销毁见 destroy_conversation_sandbox"""
        if self._stopped:
            return
        await self._client.close()
        self._stopped = True
        if LIVE_SANDBOXES.get(self._conversation_id) is self:
            LIVE_SANDBOXES.pop(self._conversation_id, None)

    async def list_entries(self, *, path: str = '.') -> list[dict[str, object]]:
        """
        列出工作区目录项

        :param path: 相对路径
        :return:
        """
        target = resolve_sandbox_path(path)
        entries = await self._client.files.list_directory(DirectoryListEntry(path=target, depth=1))
        rows: list[dict[str, object]] = []
        for item in entries:
            is_dir = (item.entry_type or '').lower() in {'dir', 'directory'}
            rows.append({'path': _relative(item.path), 'is_dir': is_dir, 'size': None if is_dir else item.size})
        return rows

    async def _file_info(self, target: str) -> Any:
        """
        读取文件元数据并拒绝目录，文件不存在时 SDK 抛出 404 而不是返回空

        :param target: 工作区内的绝对路径
        :return:
        """
        try:
            info = (await self._client.files.get_file_info([target])).get(target)
        except SandboxApiException as exc:
            if exc.status_code == 404:
                raise errors.RequestError(msg='文件不存在') from exc
            raise
        if info is None:
            raise errors.RequestError(msg='文件不存在')
        if (info.entry_type or '').lower() in {'dir', 'directory'}:
            raise errors.RequestError(msg='路径是目录，请指定文件')
        return info

    async def _require_text_size(self, target: str) -> None:
        """
        读取前按元数据拒绝目录和超限文件，避免把大文件整体拉进内存

        :param target: 工作区内的绝对路径
        :return:
        """
        info = await self._file_info(target)
        if info.size > settings.AI_BUDDY_AGENT_MAX_FILE_BYTES:
            raise errors.RequestError(msg='文件过大，请缩小范围或拆分读取')

    async def read_file(
        self, *, path: str, offset: int = 0, limit: int | None = None, line_numbers: bool = True
    ) -> str:
        """
        读取工作区文件

        :param path: 相对路径
        :param offset: 起始行，从 0 计
        :param limit: 最多返回行数
        :param line_numbers: 是否输出行号
        :return:
        """
        target = resolve_sandbox_path(path)
        await self._require_text_size(target)
        text = await self._client.files.read_file(target)
        if not line_numbers:
            lines = text.splitlines(keepends=True)
            start = max(offset, 0)
            end = None if limit is None else start + max(limit, 0)
            return ''.join(lines[start:end])
        lines = text.splitlines()
        start = max(offset, 0)
        end = len(lines) if limit is None else min(len(lines), start + max(limit, 0))
        numbered = [f'{index + 1}\t{line}' for index, line in enumerate(lines[start:end], start=start)]
        return '\n'.join(numbered)

    async def write_file(self, *, path: str, content: str) -> str:
        """
        写入工作区文件

        :param path: 相对路径
        :param content: 文件内容
        :return:
        """
        if len(content.encode('utf-8')) > settings.AI_BUDDY_AGENT_MAX_FILE_BYTES:
            raise errors.RequestError(msg='写入内容超过文件大小上限')
        target = resolve_sandbox_path(path)
        parent = normpath(join(target, '..'))
        if parent.startswith(WORKSPACE_ROOT):
            await self._client.files.create_directories([WriteEntry(path=parent, mode=755)])
        await self._client.files.write_file(target, content, mode=644)
        return f'已写入 {_relative(target)}'

    async def write_input_file(self, *, path: str, content: bytes) -> str:
        """
        通过 SDK 字节接口导入附件，临时写入成功后再替换目标

        :param path: 受限的 inbound 路径
        :param content: 附件原始字节
        :return:
        """
        digest = hashlib.sha256(content).hexdigest()
        if len(content) > INPUT_ATTACHMENT_MAX_BYTES or not re.fullmatch(
            rf'inbound/{digest}-[A-Za-z0-9][A-Za-z0-9._-]{{0,119}}', path
        ):
            raise errors.RequestError(msg='附件路径或大小无效')
        target = resolve_sandbox_path(path)
        temporary = f'{target}.{uuid4().hex}.tmp'
        await self._client.files.create_directories([WriteEntry(path=f'{WORKSPACE_ROOT}/inbound', mode=700)])
        try:
            await self._client.files.write_file(temporary, content, mode=600)
            await self._client.files.move_files([MoveEntry(src=temporary, dest=target)])
        finally:
            with contextlib.suppress(Exception):
                await self._client.files.delete_files([temporary])
        return json.dumps({'path': path, 'size': len(content), 'sha256': digest}, ensure_ascii=False)

    async def read_bytes(self, *, path: str, max_bytes: int) -> bytes:
        """
        读取工作区文件原始字节，先按元数据拒绝目录和超限文件

        :param path: 相对路径
        :param max_bytes: 字节数上限
        :return:
        """
        target = resolve_sandbox_path(path)
        info = await self._file_info(target)
        if info.size > max_bytes:
            raise errors.RequestError(msg='文件超过交付大小上限')
        return await self._client.files.read_bytes(target)

    async def edit_file(self, *, path: str, old_text: str, new_text: str) -> str:
        """
        精确替换工作区文件片段

        :param path: 相对路径
        :param old_text: 原文本
        :param new_text: 新文本
        :return:
        """
        target = resolve_sandbox_path(path)
        await self._require_text_size(target)
        text = await self._client.files.read_file(target)
        count = text.count(old_text)
        if count == 0:
            raise errors.RequestError(msg='未找到要替换的文本')
        if count > 1:
            raise errors.RequestError(msg='匹配到多处相同文本，请提供更精确的片段')
        updated = text.replace(old_text, new_text, 1)
        if len(updated.encode('utf-8')) > settings.AI_BUDDY_AGENT_MAX_FILE_BYTES:
            raise errors.RequestError(msg='编辑后内容超过文件大小上限')
        await self._client.files.replace_contents([
            ContentReplaceEntry(path=target, old_content=old_text, new_content=new_text)
        ])
        return f'已编辑 {_relative(target)}'

    async def run_bash(self, *, command: str) -> str:
        """
        在工作区执行命令，输出受上限、时限和取消处理约束

        :param command: shell 命令
        :return:
        """
        result = await self.run_command(command=command)
        code = result.exit_code if result.exit_code is not None else -1
        return f'exit {code}\n{result.stdout}{result.stderr}'.rstrip()

    async def git_status(self) -> str:
        """读取 OpenSandbox 工作区 Git 状态"""
        return await self.run_bash(command=_git_command('status'))

    async def run_tests(self, *, command: str, timeout: float | None = None) -> AIBuddyCommandResult:
        """
        通过受控命令协议执行已确认的测试命令

        :param command: 已确认的测试命令
        :param timeout: 超时秒数
        :return:
        """
        return await self.run_command(command=command, timeout=timeout)

    async def run_command(self, *, command: str, timeout: float | None = None) -> AIBuddyCommandResult:
        """
        通过 SDK 原生事件有界收集命令输出和退出状态

        :param command: 已确认的命令
        :param timeout: 执行时限
        :return:
        """
        params = AIBuddyCommandParam(command=command)
        deadline = (
            min(timeout, settings.AI_BUDDY_AGENT_BASH_TIMEOUT_SECONDS)
            if timeout is not None
            else settings.AI_BUDDY_AGENT_BASH_TIMEOUT_SECONDS
        )
        started_at = datetime.now(UTC).isoformat()
        started = asyncio.get_running_loop().time()
        execution_id: str | None = None
        output: dict[str, list[str]] = {'stdout': [], 'stderr': []}
        output_bytes = 0
        truncated = False

        async def initialized(event: ExecutionInit) -> None:  # ruff: ignore[unused-async]
            """
            保留执行标识供限额或取消时中断进程

            :param event: 执行事件
            :return:
            """
            nonlocal execution_id
            execution_id = event.id

        async def capture(message: OutputMessage) -> None:  # ruff: ignore[unused-async]
            """
            累计两条输出流的 UTF-8 字节并在超限时停止读取

            :param message: 输出消息
            :return:
            """
            nonlocal output_bytes, truncated
            encoded = message.text.encode()
            available = COMMAND_OUTPUT_MAX_BYTES - output_bytes
            output['stderr' if message.is_error else 'stdout'].append(encoded[:available].decode(errors='ignore'))
            output_bytes += min(len(encoded), available)
            if len(encoded) > available:
                truncated = True
                raise errors.RequestError(msg='测试输出超过 512 KiB，已停止收集并请求中断命令')

        result = None
        exit_code = None
        reason = AIBuddyCommandReason.execution_error
        try:
            async with asyncio.timeout(deadline):
                result = await self._client.commands.run(
                    params.command,
                    opts=RunCommandOpts(
                        working_directory=WORKSPACE_ROOT,
                        timeout=timedelta(seconds=deadline),
                    ),
                    handlers=ExecutionHandlers(
                        on_init=initialized, on_stdout=capture, on_stderr=capture, skip_accumulation=True
                    ),
                )
            exit_code = result.exit_code if result.exit_code is not None and result.exit_code >= 0 else None
            # execd 正常非零退出只发送 CommandExecError，SDK 已将其转换为原生退出码
            completed = exit_code is not None and (
                result.error is None or (result.error.name == 'CommandExecError' and exit_code > 0)
            )
            reason = AIBuddyCommandReason.completed if completed else AIBuddyCommandReason.execution_error
        except (TimeoutError, SandboxTimeoutException):
            reason = AIBuddyCommandReason.deadline
        except SandboxConnectionException:
            reason = AIBuddyCommandReason.connection_error
        except Exception:
            reason = AIBuddyCommandReason.output_limit if truncated else AIBuddyCommandReason.execution_error
        finally:
            duration_ms = int((asyncio.get_running_loop().time() - started) * 1000)
            if result is None and execution_id:
                with contextlib.suppress(Exception):
                    with anyio.move_on_after(3, shield=True):
                        await self._client.commands.interrupt(execution_id)

        return AIBuddyCommandResult(
            command=params.command,
            exit_code=exit_code,
            stdout=''.join(output['stdout']),
            stderr=''.join(output['stderr']),
            reason=AIBuddyCommandReason.output_limit if truncated else reason,
            started_at=started_at,
            duration_ms=duration_ms,
            truncated=truncated,
            output_complete=reason == AIBuddyCommandReason.completed and not truncated,
            result_available=result is not None,
        )

    async def git_diff(self, *, scope: Literal['all', 'staged', 'unstaged'] = 'all') -> str:
        """
        按范围读取 OpenSandbox 工作区未提交差异

        :param scope: 差异范围
        :return:
        """
        return await self.run_bash(command=_git_command('diff', scope=scope))

    async def run_background(self, *, command: str, env: dict[str, str] | None = None) -> str:
        """
        在工作区后台执行命令

        :param command: shell 命令
        :param env: 额外环境变量
        :return:
        """
        stripped = command.strip()
        if not stripped:
            raise errors.RequestError(msg='命令不能为空')
        execution = await self._client.commands.run(
            stripped,
            opts=RunCommandOpts(background=True, working_directory=WORKSPACE_ROOT, envs=env),
        )
        if not execution.id:
            raise errors.RequestError(msg='后台命令未返回任务 ID')
        return execution.id

    async def get_background_task(self, *, task_id: str, cursor: int | None = None) -> AIBuddyBackgroundTaskDetail:
        """
        查询后台命令状态并增量读取输出

        :param task_id: 后台命令任务 ID
        :param cursor: 日志游标
        :return:
        """
        try:
            status = await self._client.commands.get_command_status(task_id)
            logs = await self._client.commands.get_background_command_logs(task_id, cursor)
        except SandboxConnectionException as exc:
            raise errors.RequestError(msg='后台命令任务不存在或沙箱不可用') from exc
        return AIBuddyBackgroundTaskDetail(
            task_id=task_id,
            running=bool(status.running),
            exit_code=status.exit_code,
            error=status.error,
            started_at=status.started_at,
            finished_at=status.finished_at,
            logs=logs.content[-COMMAND_OUTPUT_MAX_BYTES:],
            cursor=logs.cursor,
        )

    async def stop_background(self, *, task_id: str) -> None:
        """
        中断后台命令

        :param task_id: 后台命令任务 ID
        :return:
        """
        await self._client.commands.interrupt(task_id)

    async def get_endpoint(self, port: int) -> tuple[str, dict[str, str]]:
        """
        解析沙箱端口映射

        :param port: 沙箱内端口
        :return:
        """
        last_error = '沙箱端口未就绪'
        for _ in range(50):
            try:
                # 仅端口查询使用直连，文件与命令保留 server proxy 配置
                endpoint = await self._endpoints.get_sandbox_endpoint(self._client.id, port, use_server_proxy=False)
                raw = (endpoint.endpoint or '').strip()
                if raw:
                    parsed = urlparse(raw if '://' in raw else f'http://{raw}')
                    host = parsed.hostname
                    if host:
                        # 宿主机 SDK 使用配置中的地址替换容器专用域名
                        if host == 'host.docker.internal':
                            domain = settings.AI_BUDDY_OPENSANDBOX_DOMAIN.strip()
                            client_url = urlparse(
                                domain if '://' in domain else f'{settings.AI_BUDDY_OPENSANDBOX_PROTOCOL}://{domain}'
                            )
                            host = client_url.hostname or '127.0.0.1'
                        base = f'{parsed.scheme or "http"}://{host}'
                        if parsed.port:
                            base = f'{base}:{parsed.port}'
                        return base, dict(endpoint.headers)
            except Exception as exc:
                last_error = str(exc)
            await asyncio.sleep(0.1)
        raise errors.RequestError(msg=f'沙箱端口映射超时: {last_error}')


def _relative(path: str) -> str:
    """
    将沙箱工作区绝对路径转换为相对路径

    :param path: 文件路径
    :return:
    """
    if path == WORKSPACE_ROOT:
        return '.'
    prefix = f'{WORKSPACE_ROOT}/'
    if path.startswith(prefix):
        return path[len(prefix) :]
    return path
