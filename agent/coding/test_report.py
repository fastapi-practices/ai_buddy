from __future__ import annotations

import asyncio
import json

from typing import TYPE_CHECKING

import anyio

from backend.common.exception import errors
from backend.common.log import log
from backend.database.db import async_db_session
from backend.plugin.ai_buddy.enums import (
    AIBuddyArtifactKind,
    AIBuddyCommandReason,
    AIBuddyExecutionBackend,
    AIBuddyTestReportArchiveStatus,
)
from backend.plugin.ai_buddy.schema.artifact import CreateAIBuddyArtifactParam
from backend.plugin.ai_buddy.schema.command import AIBuddyCommandParam, AIBuddyCommandResult
from backend.plugin.ai_buddy.schema.test_report import AIBuddyTestReportArchive, GetAIBuddyTestReportDetail
from backend.plugin.ai_buddy.service.artifact_service import ai_buddy_artifact_service

if TYPE_CHECKING:
    from backend.plugin.ai_buddy.agent.coding.types import AgentRunContext

_PREVIEW_CHARS = 12000


def _unavailable_result(*, command: str, reason: AIBuddyCommandReason) -> AIBuddyCommandResult:
    """
    缺失最终响应时仅记录已知状态，不伪造退出码或进程输出

    :param command: 测试命令
    :param reason: 结果缺失原因
    :return:
    """
    return AIBuddyCommandResult(
        command=command,
        exit_code=None,
        stdout='',
        stderr='',
        reason=reason,
        started_at=None,
        duration_ms=None,
        truncated=False,
        output_complete=False,
        result_available=False,
    )


async def _archive_report(*, ctx: AgentRunContext, report: GetAIBuddyTestReportDetail) -> None:
    """提交可下载的 Markdown 事实报告并明确记录归档失败

    :param ctx: 运行上下文
    :param report: 待归档的测试事实
    :return:
    """
    metadata = report.model_dump(exclude={'archive', 'requested_command', 'execution', 'preview_truncated'})
    metadata['execution'] = report.execution.model_dump(exclude={'command', 'stdout', 'stderr'})
    content = [
        '# 测试命令执行报告',
        '本报告记录实际执行事实，不推断测试用例数量或通过率',
        '```json\n' + json.dumps(metadata, ensure_ascii=False, indent=2) + '\n```',
    ]
    for title, value in (
        ('请求命令', report.requested_command),
        ('实际命令', report.execution.command),
        ('标准输出', report.execution.stdout),
        ('标准错误输出', report.execution.stderr),
    ):
        content.extend([f'## {title}', '\n'.join('    ' + line for line in (value or '（空）').splitlines())])
    if not report.execution.result_available:
        content.append('未取得执行器最终结果，退出码未知；保留的输出可能为空或不完整，不能据此判断命令成功')
    if not report.execution.output_complete:
        content.append('输出不完整；取消、中断、输出上限或连接错误之后的最终输出可能丢失')

    try:
        async with asyncio.timeout(15):
            async with async_db_session.begin() as db:
                artifact = await ai_buddy_artifact_service.create(
                    db=db,
                    user_id=ctx.user_id,
                    obj=CreateAIBuddyArtifactParam(
                        title=f'测试报告：{report.requested_command.splitlines()[0][:80]}',
                        kind=AIBuddyArtifactKind.document,
                        content='\n\n'.join(content),
                    ),
                )
                artifact_id = artifact.id
        report.archive = AIBuddyTestReportArchive(
            status=AIBuddyTestReportArchiveStatus.saved, artifact_id=str(artifact_id), error=None
        )
    except Exception as exc:
        detail = exc.msg[:2000] if isinstance(exc, errors.BaseExceptionError) else '报告保存失败，请检查服务状态'
        report.archive = AIBuddyTestReportArchive(
            status=AIBuddyTestReportArchiveStatus.failed, artifact_id=None, error=detail
        )
        log.warning('AI Buddy 测试报告归档失败 run_id={} error_type={} error={}', ctx.run_id, type(exc).__name__, exc)


async def run_tests_and_archive(*, ctx: AgentRunContext, command: str) -> str:
    """执行一次显式测试命令，归档完整捕获结果，再返回有界预览

    :param ctx: 运行上下文
    :param command: 已确认的测试命令
    :return:
    """
    params = AIBuddyCommandParam(command=command)
    report = GetAIBuddyTestReportDetail(
        conversation_id=ctx.conversation_id,
        run_id=ctx.run_id,
        workspace_id=ctx.workspace_id,
        execution_backend=ctx.sandbox.execution_backend,
        requested_command=params.command,
        execution=_unavailable_result(command=params.command, reason=AIBuddyCommandReason.execution_error),
        archive=AIBuddyTestReportArchive(
            status=AIBuddyTestReportArchiveStatus.failed, artifact_id=None, error='尚未归档'
        ),
    )
    cancellation: asyncio.CancelledError | None = None
    try:
        report.execution = await ctx.sandbox.run_tests(command=params.command)
    except asyncio.CancelledError as exc:
        cancellation = exc
        report.execution = _unavailable_result(command=params.command, reason=AIBuddyCommandReason.cancelled)
    except TimeoutError:
        report.execution = _unavailable_result(command=params.command, reason=AIBuddyCommandReason.deadline)
    except errors.RequestError as exc:
        reason = (
            AIBuddyCommandReason.deadline
            if isinstance(exc.__cause__, TimeoutError)
            else AIBuddyCommandReason.connection_error
        )
        report.execution = _unavailable_result(command=params.command, reason=reason)
    except Exception:
        reason = (
            AIBuddyCommandReason.connection_error
            if ctx.sandbox.execution_backend == AIBuddyExecutionBackend.local
            else AIBuddyCommandReason.execution_error
        )
        report.execution = _unavailable_result(command=params.command, reason=reason)

    archive_task = asyncio.create_task(_archive_report(ctx=ctx, report=report))
    try:
        with anyio.move_on_after(5 if cancellation is not None else 20, shield=True):
            await asyncio.shield(archive_task)
    except asyncio.CancelledError as exc:
        cancellation = exc
        with anyio.move_on_after(5, shield=True):
            await asyncio.shield(archive_task)
    finally:
        if not archive_task.done():
            archive_task.cancel()
            with anyio.move_on_after(1, shield=True):
                await asyncio.gather(archive_task, return_exceptions=True)
            report.archive = AIBuddyTestReportArchive(
                status=AIBuddyTestReportArchiveStatus.failed, artifact_id=None, error='报告归档被中断'
            )
            log.warning('AI Buddy 测试报告归档被中断 run_id={}', ctx.run_id)
    if cancellation is not None:
        raise cancellation

    payload = report.model_dump()
    stdout = report.execution.stdout[:_PREVIEW_CHARS]
    stderr = report.execution.stderr[: _PREVIEW_CHARS - len(stdout)]
    payload['execution']['stdout'] = stdout
    payload['execution']['stderr'] = stderr
    payload['preview_truncated'] = len(stdout) + len(stderr) < len(report.execution.stdout) + len(
        report.execution.stderr
    )
    return json.dumps(payload, ensure_ascii=False)
