import asyncio
import contextlib
import hashlib
import json
import re

from collections.abc import Awaitable
from datetime import UTC, datetime
from posixpath import join, normpath
from shlex import quote
from uuid import uuid4

from pydantic_ai.workspaces import (
    Workspace,
    WorkspaceError,
    WorkspaceOutputLimitError,
    WorkspaceTimeoutError,
    WorkspaceUnavailableError,
)

from backend.common.exception import errors
from backend.core.conf import settings
from backend.plugin.ai_buddy.agent.coding.sandbox import (
    _LIVE,
    _WORKSPACE,
    _git_command,
    _relative,
    resolve_sandbox_path,
)
from backend.plugin.ai_buddy.enums import (
    AIBuddyCommandReason,
    AIBuddyExecutionBackend,
    AIBuddyPermissionMode,
)
from backend.plugin.ai_buddy.schema.command import (
    COMMAND_OUTPUT_MAX_BYTES,
    AIBuddyBackgroundTaskDetail,
    AIBuddyCommandParam,
    AIBuddyCommandResult,
)

_BACKGROUND_DIR = f'{_WORKSPACE}/.fba/background'
_TASK_ID = re.compile(r'^[a-f0-9]{32}$')


class WorkspaceSandbox:
    """把任意 Pydantic AI Workspace 适配为编码工作区，沙箱服务商可通过配置随时切换"""

    def __init__(
        self,
        workspace: Workspace,
        *,
        provider: str,
        conversation_id: str,
        user_id: int | None = None,
        permission_mode: AIBuddyPermissionMode = AIBuddyPermissionMode.ask,
    ) -> None:
        """
        绑定已创建或已接回的 Workspace

        :param workspace: Pydantic AI 工作区
        :param provider: 沙箱服务商
        :param conversation_id: 对话 ID
        :param user_id: 用户 ID
        :param permission_mode: 权限模式
        :return:
        """
        self._workspace = workspace
        self.provider = provider
        self._conversation_id = conversation_id
        self.execution_backend = AIBuddyExecutionBackend.sandbox
        self.cwd = _WORKSPACE
        self.user_id = user_id
        self.permission_mode = permission_mode

    async def stop(self) -> None:
        """从本进程摘除，沙箱本身由服务商的空闲与寿命策略回收，销毁见 destroy_conversation_sandbox"""
        if _LIVE.get(self._conversation_id) is self:
            _LIVE.pop(self._conversation_id, None)

    async def list_entries(self, *, path: str = '.') -> list[dict[str, object]]:
        """
        列出工作区目录项

        :param path: 相对路径
        :return:
        """
        entries = await self._call(self._workspace.list_dir(resolve_sandbox_path(path)))
        return [
            {'path': _relative(item.path), 'is_dir': item.is_dir, 'size': None if item.is_dir else item.size}
            for item in entries
        ]

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
        text = await self._call(self._workspace.read_text(resolve_sandbox_path(path)))
        if len(text.encode('utf-8')) > settings.AI_BUDDY_AGENT_MAX_FILE_BYTES:
            raise errors.RequestError(msg='文件过大，请缩小范围或拆分读取')
        start = max(offset, 0)
        if not line_numbers:
            end = None if limit is None else start + max(limit, 0)
            return ''.join(text.splitlines(keepends=True)[start:end])
        lines = text.splitlines()
        end = len(lines) if limit is None else min(len(lines), start + max(limit, 0))
        return '\n'.join(f'{index + 1}\t{line}' for index, line in enumerate(lines[start:end], start=start))

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
        await self._call(self._workspace.write_text(target, content))
        return f'已写入 {_relative(target)}'

    async def write_input_file(self, *, path: str, content: bytes) -> str:
        """
        导入附件，先写临时文件再原子替换目标

        :param path: 受限的 inbound 路径
        :param content: 附件原始字节
        :return:
        """
        digest = hashlib.sha256(content).hexdigest()
        if len(content) > 10 * 1024 * 1024 or not re.fullmatch(
            rf'inbound/{digest}-[A-Za-z0-9][A-Za-z0-9._-]{{0,119}}', path
        ):
            raise errors.RequestError(msg='附件路径或大小无效')
        target = resolve_sandbox_path(path)
        temporary = f'{target}.{uuid4().hex}.tmp'
        await self._call(self._workspace.write_bytes(temporary, content))
        try:
            moved = await self._call(self._workspace.run(['mv', '-f', temporary, target], timeout=30))
            if moved.exit_code != 0:
                raise errors.RequestError(msg='附件导入失败')
        except BaseException:
            with contextlib.suppress(Exception):
                await self._workspace.remove(temporary)
            raise
        return json.dumps({'path': path, 'size': len(content), 'sha256': digest}, ensure_ascii=False)

    async def read_bytes(self, *, path: str, max_bytes: int) -> bytes:
        """
        读取工作区文件原始字节，先按元数据拒绝目录和超限文件

        :param path: 相对路径
        :param max_bytes: 字节数上限
        :return:
        """
        target = resolve_sandbox_path(path)
        entry = await self._call(self._workspace.stat(target))
        if entry.is_dir:
            raise errors.RequestError(msg='路径是目录，请指定文件')
        if (entry.size or 0) > max_bytes:
            raise errors.RequestError(msg='文件超过交付大小上限')
        return await self._call(self._workspace.read_bytes(target))

    async def edit_file(self, *, path: str, old_text: str, new_text: str) -> str:
        """
        精确替换工作区文件片段

        :param path: 相对路径
        :param old_text: 原文本
        :param new_text: 新文本
        :return:
        """
        target = resolve_sandbox_path(path)
        text = await self._call(self._workspace.read_text(target))
        count = text.count(old_text)
        if count == 0:
            raise errors.RequestError(msg='未找到要替换的文本')
        if count > 1:
            raise errors.RequestError(msg='匹配到多处相同文本，请提供更精确的片段')
        updated = text.replace(old_text, new_text, 1)
        if len(updated.encode('utf-8')) > settings.AI_BUDDY_AGENT_MAX_FILE_BYTES:
            raise errors.RequestError(msg='编辑后内容超过文件大小上限')
        await self._call(self._workspace.write_text(target, updated))
        return f'已编辑 {_relative(target)}'

    async def run_bash(self, *, command: str) -> str:
        """
        在工作区执行命令

        :param command: shell 命令
        :return:
        """
        result = await self.run_command(command=command)
        code = result.exit_code if result.exit_code is not None else -1
        return f'exit {code}\n{result.stdout}{result.stderr}'.rstrip()

    async def git_status(self) -> str:
        """读取工作区 Git 状态"""
        return await self.run_bash(command=_git_command('status'))

    async def git_diff(self, *, scope: str = 'all') -> str:
        """
        按范围读取未提交差异

        :param scope: 差异范围
        :return:
        """
        return await self.run_bash(command=_git_command('diff', scope=scope))

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
        执行受控命令，结果区分正常结束、超时、输出超限和环境不可用，取消会向上传播

        :param command: 已确认的命令
        :param timeout: 超时秒数
        :return:
        """
        params = AIBuddyCommandParam(command=command)
        limit = settings.AI_BUDDY_AGENT_BASH_TIMEOUT_SECONDS
        deadline = min(timeout, limit) if timeout is not None else limit
        started_at = datetime.now(UTC).isoformat()
        started = asyncio.get_running_loop().time()
        reason = AIBuddyCommandReason.completed
        exit_code: int | None = None
        stdout = stderr = ''
        available = True
        try:
            result = await self._workspace.run(params.command, shell=True, timeout=deadline)
            exit_code, stdout, stderr = result.exit_code, result.stdout, result.stderr
        except WorkspaceTimeoutError as exc:
            reason, stdout, stderr, available = AIBuddyCommandReason.deadline, exc.stdout, exc.stderr, False
        except WorkspaceOutputLimitError as exc:
            reason, stdout, stderr, available = AIBuddyCommandReason.output_limit, exc.stdout, exc.stderr, False
        except WorkspaceUnavailableError:
            reason, available = AIBuddyCommandReason.connection_error, False
        except WorkspaceError:
            reason, available = AIBuddyCommandReason.execution_error, False
        truncated = len(stdout.encode()) + len(stderr.encode()) > COMMAND_OUTPUT_MAX_BYTES
        if truncated:
            stdout = stdout.encode()[: COMMAND_OUTPUT_MAX_BYTES // 2].decode(errors='ignore')
            stderr = stderr.encode()[: COMMAND_OUTPUT_MAX_BYTES // 2].decode(errors='ignore')
            reason = AIBuddyCommandReason.output_limit
        return AIBuddyCommandResult(
            command=params.command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            reason=reason,
            started_at=started_at,
            duration_ms=int((asyncio.get_running_loop().time() - started) * 1000),
            truncated=truncated or reason == AIBuddyCommandReason.output_limit,
            output_complete=reason == AIBuddyCommandReason.completed,
            result_available=available,
        )

    async def run_background(self, *, command: str, env: dict[str, str] | None = None) -> str:
        """
        在工作区后台执行命令，输出写入工作区内的日志文件，退出码写入退出文件

        :param command: shell 命令
        :param env: 额外环境变量
        :return:
        """
        stripped = AIBuddyCommandParam(command=command).command.strip()
        task_id = uuid4().hex
        base = f'{_BACKGROUND_DIR}/{task_id}'
        inner = quote(f'{stripped}\necho $? > {base}.exit')
        script = (
            f'mkdir -p {_BACKGROUND_DIR}; S=; command -v setsid >/dev/null 2>&1 && S=setsid; '
            f'$S nohup sh -c {inner} > {base}.log 2>&1 < /dev/null & echo $! > {base}.pid'
        )
        result = await self._call(self._workspace.run(script, shell=True, env=env, timeout=30))
        if result.exit_code != 0:
            raise errors.RequestError(msg='后台命令启动失败')
        return task_id

    async def get_background_task(self, *, task_id: str, cursor: int | None = None) -> AIBuddyBackgroundTaskDetail:
        """
        查询后台命令状态并按字节游标增量读取输出

        :param task_id: 后台命令任务 ID
        :param cursor: 日志字节游标
        :return:
        """
        base = self._task_base(task_id)
        offset = max(cursor or 0, 0)
        script = (
            f'[ -e {base}.pid ] || {{ echo MISSING; exit 0; }}; '
            f'if [ -f {base}.exit ]; then echo "EXIT:$(cat {base}.exit)"; else echo RUNNING; fi; '
            f'tail -c +{offset + 1} {base}.log | head -c {COMMAND_OUTPUT_MAX_BYTES}'
        )
        result = await self._call(self._workspace.run(script, shell=True, timeout=30))
        head, _, body = result.stdout.partition('\n')
        if head == 'MISSING':
            raise errors.NotFoundError(msg='后台命令任务不存在')
        exit_code = int(head.removeprefix('EXIT:')) if head.startswith('EXIT:') and head[5:].isdigit() else None
        return AIBuddyBackgroundTaskDetail(
            task_id=task_id,
            running=head == 'RUNNING',
            exit_code=exit_code,
            error=None,
            started_at=None,
            finished_at=None,
            logs=body,
            cursor=offset + len(body.encode()),
        )

    async def stop_background(self, *, task_id: str) -> None:
        """
        中断后台命令及其进程组，并补写退出文件

        :param task_id: 后台命令任务 ID
        :return:
        """
        base = self._task_base(task_id)
        script = (
            f'[ -e {base}.pid ] || exit 3; P=$(cat {base}.pid); '
            'kill -TERM -- -$P 2>/dev/null || kill -TERM $P 2>/dev/null; '
            f'[ -f {base}.exit ] || echo 143 > {base}.exit'
        )
        result = await self._call(self._workspace.run(script, shell=True, timeout=30))
        if result.exit_code == 3:
            raise errors.NotFoundError(msg='后台命令任务不存在')

    async def get_endpoint(self, port: int) -> tuple[str, dict[str, str]]:
        """
        查询工作区进程的可访问地址，通用沙箱适配暂不提供

        :param port: 端口号
        :return:
        """
        raise errors.RequestError(msg=f'沙箱服务商 {self.provider} 暂不支持端口访问，请使用 OpenSandbox')

    @staticmethod
    def _task_base(task_id: str) -> str:
        """
        校验任务 ID 并返回其状态文件前缀，防止路径拼接逃逸

        :param task_id: 后台命令任务 ID
        :return:
        """
        if not _TASK_ID.fullmatch(task_id):
            raise errors.RequestError(msg='后台命令任务 ID 无效')
        return normpath(join(_BACKGROUND_DIR, task_id))

    @staticmethod
    async def _call[T](awaitable: Awaitable[T]) -> T:
        """
        把工作区异常转换为业务错误，沙箱不存在或不可用时提示用户重新建立

        :param awaitable: 工作区调用
        :return:
        """
        try:
            return await awaitable
        except WorkspaceUnavailableError as exc:
            raise errors.RequestError(msg='沙箱已不可用，请重试以建立新的沙箱') from exc
        except WorkspaceTimeoutError as exc:
            raise errors.RequestError(msg='沙箱操作超时') from exc
        except FileNotFoundError as exc:
            raise errors.RequestError(msg='文件或目录不存在') from exc
        except (IsADirectoryError, NotADirectoryError, PermissionError) as exc:
            raise errors.RequestError(msg=f'路径不可访问：{type(exc).__name__}') from exc
        except WorkspaceError as exc:
            raise errors.RequestError(msg=f'沙箱操作失败：{exc}') from exc
