import shlex

from collections.abc import Mapping

from pydantic_ai.workspaces import (
    CommandResult,
    WorkspaceCommand,
    WorkspaceError,
    WorkspaceOutputLimitError,
    WorkspaceRef,
    WorkspaceTimeoutError,
)

from backend.plugin.ai_buddy.agent.coding.sandbox import CodingSandbox
from backend.plugin.ai_buddy.schema.command import COMMAND_OUTPUT_MAX_BYTES


class CodingWorkspace:
    """将现有受控执行环境适配到 SDK 工作区，不在宿主启动进程"""

    def __init__(self, sandbox: CodingSandbox, *, conversation_id: str) -> None:
        """
        绑定本轮已授权的工作区

        :param sandbox: 本轮执行环境
        :param conversation_id: 对话 ID
        :return:
        """
        self.sandbox = sandbox
        self.ref = WorkspaceRef(provider='buddy', id=conversation_id)

    async def working_dir(self) -> str:
        """返回两种执行后端共用的工作区路径"""
        return '/workspace'

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        """
        复用结构化命令执行的取消、输出限制和真实退出状态

        :param command: 命令字符串或参数列表
        :param shell: 是否使用 Shell 语法
        :param env: 额外环境变量
        :param timeout: SDK 请求的执行时限
        :return:
        """
        if shell != isinstance(command, str):
            raise TypeError('Shell 模式与命令参数类型不匹配')
        if env:
            raise WorkspaceError('搜索工作区不接受额外环境变量')
        script = command if isinstance(command, str) else shlex.join(command)
        result = await self.sandbox.run_command(command=script, timeout=timeout)
        if result.truncated:
            raise WorkspaceOutputLimitError('搜索输出超过工作区限制，请缩小目录范围', limit=COMMAND_OUTPUT_MAX_BYTES)
        if result.reason == 'deadline':
            raise WorkspaceTimeoutError('工作区搜索执行超时', stdout=result.stdout, stderr=result.stderr)
        if not result.output_complete or result.exit_code is None:
            raise WorkspaceError(result.stderr or '工作区搜索未完整执行')
        return CommandResult(exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr)
