import asyncio
import hashlib

from collections.abc import Awaitable, Callable
from typing import Any

import anyio

from opensandbox.exceptions import SandboxException
from pydantic_ai import AgentRunResult, RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapRunHandler
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import WorkspaceError

from backend.common.exception import errors
from backend.common.log import log
from backend.core.conf import settings
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.agent.coding.attachments import input_attachment_path
from backend.plugin.ai_buddy.agent.coding.delivery import deliver_sandbox_file
from backend.plugin.ai_buddy.agent.coding.sandbox import CodingSandbox
from backend.plugin.ai_buddy.agent.coding.sandbox_providers import create_coding_sandbox
from backend.plugin.ai_buddy.agent.work.capabilities.base import function_tools_allowed
from backend.plugin.ai_buddy.dataclasses import CapabilityContext, CapabilityResult, ChatAgentDeps
from backend.plugin.ai_buddy.enums import (
    AIBuddyAgentMode,
    AIBuddyArtifactKind,
    AIBuddyChatGenerationType,
    AIBuddyCommandReason,
    AIBuddyExecutionBackend,
    AIBuddyOrigin,
    AIBuddyPermissionMode,
)
from backend.plugin.ai_buddy.schema.chat import AIBuddyChatForwardedPropsParam
from backend.plugin.ai_buddy.service.skill_service import ai_buddy_skill_service
from backend.plugin.ai_buddy.utils.office_text import input_attachments

_SKILL_ROOT = 'skills'
_SKIPPED_PREVIEW = 10


def sandbox_tools_enabled(ctx: CapabilityContext) -> bool:
    """
    判断本轮是否装配沙箱工具，仅工作模式的网页来源装配，IM 没有审批回调、定时任务无人值守

    :param ctx: 能力构建上下文
    :return:
    """
    return (
        ctx.user_id is not None
        and bool(ctx.conversation_id)
        and ctx.origin == AIBuddyOrigin.web
        and isinstance(ctx.forwarded_props, AIBuddyChatForwardedPropsParam)
        and ctx.forwarded_props.agent_mode == AIBuddyAgentMode.work
        and ctx.forwarded_props.generation_type == AIBuddyChatGenerationType.text
        and function_tools_allowed(
            adapter=ctx.adapter, supports_tools=ctx.supports_tools, has_builtin_tools=ctx.has_builtin_tools
        )
    )


class BuddySandbox(AbstractCapability[ChatAgentDeps]):
    """工作模式的服务端沙箱工具，首次使用时才打开沙箱，每轮结束只释放本进程连接，沙箱实例保留供下一轮接回"""

    def __init__(self) -> None:
        """创建沙箱工具集，工具以实例方法注册，共享本轮打开的沙箱"""
        self._sandbox: CodingSandbox | None = None
        self._lock = asyncio.Lock()
        self._toolset = FunctionToolset[ChatAgentDeps]()
        for tool in (
            self.read,
            self.write,
            self.edit,
            self.ls,
            self.bash,
            self.install_skill,
            self.import_attachment,
            self.deliver_file,
        ):
            self._toolset.tool(tool)

    def get_toolset(self) -> FunctionToolset[ChatAgentDeps]:
        """返回沙箱工具集"""
        return self._toolset

    async def wrap_run(self, ctx: RunContext[ChatAgentDeps], *, handler: WrapRunHandler) -> AgentRunResult[Any]:
        """
        运行结束或中断时释放沙箱连接

        :param ctx: 运行上下文
        :param handler: SDK 运行处理器
        :return:
        """
        try:
            return await handler()
        finally:
            if self._sandbox is not None:
                with anyio.move_on_after(5, shield=True):
                    await self._sandbox.stop()
                self._sandbox = None

    async def read(self, ctx: RunContext[ChatAgentDeps], path: str, offset: int = 0, limit: int | None = None) -> str:
        """
        读取沙箱工作区内的文本文件，返回带行号的内容

        :param ctx: 运行上下文
        :param path: 工作区内的文件路径
        :param offset: 起始行号，从 0 开始
        :param limit: 最多读取的行数，为空读取到文件末尾
        :return:
        """
        return await self._run(ctx, lambda sandbox: sandbox.read_file(path=path, offset=offset, limit=limit))

    async def write(self, ctx: RunContext[ChatAgentDeps], path: str, content: str) -> str:
        """
        把文本写入沙箱工作区文件，目录不存在时自动创建，同名文件会被覆盖

        :param ctx: 运行上下文
        :param path: 工作区内的文件路径
        :param content: 文件内容
        :return:
        """
        return await self._run(ctx, lambda sandbox: sandbox.write_file(path=path, content=content))

    async def edit(self, ctx: RunContext[ChatAgentDeps], path: str, old_text: str, new_text: str) -> str:
        """
        精确替换沙箱工作区文件中的一段文本，old_text 必须在文件中唯一

        :param ctx: 运行上下文
        :param path: 工作区内的文件路径
        :param old_text: 要替换的原文本
        :param new_text: 替换后的新文本
        :return:
        """
        return await self._run(ctx, lambda sandbox: sandbox.edit_file(path=path, old_text=old_text, new_text=new_text))

    async def ls(self, ctx: RunContext[ChatAgentDeps], path: str = '.') -> str:
        """
        列出沙箱工作区目录

        :param ctx: 运行上下文
        :param path: 工作区内的目录路径，默认为根目录
        :return:
        """

        async def action(sandbox: CodingSandbox) -> str:
            """
            列出目录并区分文件与子目录

            :param sandbox: 本轮沙箱
            :return:
            """
            entries = await sandbox.list_entries(path=path)
            lines = [f'{item["path"]}/' if item['is_dir'] else f'{item["path"]} {item["size"]}B' for item in entries]
            return '\n'.join(lines) or '目录为空'

        return await self._run(ctx, action)

    async def bash(self, ctx: RunContext[ChatAgentDeps], command: str) -> str:
        """
        在沙箱工作区执行 shell 命令并返回退出码和输出；沙箱默认没有网络，不能安装依赖，也无法访问项目仓库

        :param ctx: 运行上下文
        :param command: shell 命令
        :return:
        """

        async def action(sandbox: CodingSandbox) -> str:
            """
            执行命令并拼接退出码与输出

            :param sandbox: 本轮沙箱
            :return:
            """
            result = await sandbox.run_command(command=command)
            output = f'{result.stdout}{result.stderr}'
            if result.reason != AIBuddyCommandReason.completed:
                output = f'{output}\n命令未正常完成：{result.reason}' + ('，输出已截断' if result.truncated else '')
            return f'exit {result.exit_code if result.exit_code is not None else -1}\n{output}'.rstrip()

        return await self._run(ctx, action)

    async def install_skill(self, ctx: RunContext[ChatAgentDeps], skill_id: int) -> str:
        """
        把技能包的文本文件复制到沙箱 skills/<技能名>/，之后才能执行其中的脚本；技能文档里的 SKILL_DIR 即返回的目录

        :param ctx: 运行上下文
        :param skill_id: 技能 ID
        :return:
        """

        async def action(sandbox: CodingSandbox) -> str:
            """
            读取技能包并把文本文件写入沙箱

            :param sandbox: 本轮沙箱
            :return:
            """
            async with async_db_session() as db:
                skill, files = await ai_buddy_skill_service.get_package(db=db, pk=skill_id, user_id=ctx.deps.user_id)
            root = f'{_SKILL_ROOT}/{skill.name}'
            copied = 0
            skipped: list[str] = []
            for relative, data in files:
                try:
                    text = None if data is None else data.decode('utf-8')
                except UnicodeDecodeError:
                    text = None
                if text is None or '\x00' in text or len(data) > settings.AI_BUDDY_AGENT_MAX_FILE_BYTES:
                    skipped.append(relative)
                    continue
                await sandbox.write_file(path=f'{root}/{relative}', content=text)
                copied += 1
            message = f'技能已安装到 /workspace/{root}，文档中的 SKILL_DIR 即此目录，共复制 {copied} 个文件'
            if skipped:
                preview = '、'.join(skipped[:_SKIPPED_PREVIEW])
                message += f'；以下 {len(skipped)} 个二进制或过大的文件未复制：{preview}'
            return message

        return await self._run(ctx, action)

    async def import_attachment(self, ctx: RunContext[ChatAgentDeps], sha256_prefix: str) -> str:
        """
        把用户上传的附件原始文件导入沙箱 inbound/ 目录并返回沙箱内路径，附件的 sha256 前缀见用户消息中的附件说明

        :param ctx: 运行上下文
        :param sha256_prefix: 附件 sha256 的前 8 位以上十六进制字符
        :return:
        """
        prefix = sha256_prefix.strip().lower()
        if len(prefix) < 8:
            return '错误：sha256_prefix 至少需要 8 位'
        digests = {hashlib.sha256(item.data).hexdigest(): item for item in input_attachments(ctx.messages)}
        matches = [digest for digest in digests if digest.startswith(prefix)]
        if not matches:
            return '错误：没有找到匹配的附件'
        if len(matches) > 1:
            return '错误：前缀匹配到多个附件，请提供更长的 sha256 前缀'
        attachment = digests[matches[0]]
        return await self._run(
            ctx,
            lambda sandbox: sandbox.write_input_file(path=input_attachment_path(attachment), content=attachment.data),
        )

    async def deliver_file(
        self,
        ctx: RunContext[ChatAgentDeps],
        path: str,
        title: str | None = None,
        kind: AIBuddyArtifactKind | None = None,
    ) -> str:
        """
        把沙箱工作区内要交给用户的最终文件保存为持久产物并返回产物 ID；沙箱磁盘可能被回收，依赖、日志和中间文件不要交付

        :param ctx: 运行上下文
        :param path: 工作区内的文件路径，建议放在 outbound/ 目录
        :param title: 产物标题，默认使用文件名
        :param kind: 产物类型：image 图片、video 视频、audio 音频、text 文本、document 文档、other 其他，默认推断
        :return:
        """
        return await self._run(
            ctx,
            lambda sandbox: deliver_sandbox_file(
                sandbox=sandbox,
                user_id=ctx.deps.user_id,
                conversation_id=ctx.deps.conversation_id,
                path=path,
                title=(title or '').strip() or None,
                kind=kind,
            ),
        )

    async def _run(self, ctx: RunContext[ChatAgentDeps], action: Callable[[CodingSandbox], Awaitable[str]]) -> str:
        """
        打开沙箱并执行工具动作，把业务错误和沙箱服务故障转换为工具结果，避免中断整轮运行

        :param ctx: 运行上下文
        :param action: 使用沙箱的工具动作
        :return:
        """
        try:
            return await action(await self._open(ctx))
        except errors.BaseExceptionError as exc:
            return f'错误：{exc.msg}'
        except (SandboxException, WorkspaceError, TimeoutError, OSError) as exc:
            log.warning(f'Work 沙箱调用失败: {exc!r}')
            return '错误：服务端沙箱暂不可用，请稍后重试或联系管理员检查沙箱服务'

    async def _open(self, ctx: RunContext[ChatAgentDeps]) -> CodingSandbox:
        """
        按对话接回或新建服务端沙箱，权限固定为禁止出网的 ask 级别，并发调用只打开一次

        :param ctx: 运行上下文
        :return:
        """
        async with self._lock:
            if self._sandbox is None:
                self._sandbox = await create_coding_sandbox(
                    conversation_id=ctx.deps.conversation_id,
                    user_id=ctx.deps.user_id,
                    permission_mode=AIBuddyPermissionMode.ask,
                    execution_backend=AIBuddyExecutionBackend.sandbox,
                )
            return self._sandbox


def build_sandbox_tools_capability(ctx: CapabilityContext) -> CapabilityResult:
    """
    为工作模式装配服务端沙箱工具，用于运行技能脚本生成和编辑 Office、PDF 文件

    :param ctx: 能力构建上下文
    :return:
    """
    if not sandbox_tools_enabled(ctx):
        return CapabilityResult(capability=None)
    return CapabilityResult(capability=BuddySandbox(), introduces_function_tool_source=True)
